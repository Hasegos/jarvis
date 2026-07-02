import os, shutil, uuid
from pathlib import Path

from core.constants.tool import (
    FILE_OPS_ACTIONS,
    FILE_OPS_SAFE_ACTIONS,
    FILE_OPS_READ_MAX_CHARS,
    FILE_OPS_LIST_MAX,
)
from core.logger import get_logger
from services.tool.tool_result import ok, err

logger = get_logger("tool.file_ops")

# 위험도 — needs_confirm(영역 등급별 판단)이 우선하지만, 미정의 대비 fail-safe 기본값
RISK = "destructive"

# 등급 엄격도 (move 시 src·dest 중 더 엄격한 쪽 적용)
_GRADE_RANK = {"safe": 0, "normal": 1, "strict": 2}

# 컨테이너 내부 마운트 루트. 각 영역은 {ROOT}/{별칭} 으로 자동 매핑된다.
FILE_OPS_CONTAINER_ROOT = "/data/fileops"
_FILE_OPS_GRADES = {"safe", "normal", "strict"}


# ─────────────────────────────────────
# 1. 영역 수집
# ─────────────────────────────────────
def _collect_file_ops_areas() -> dict:
    """
    FILE_OPS_{별칭}={등급}:{호스트경로} 형태 환경변수를 모두 수집한다.

    .env 파일(로컬 실행)과 os.environ(도커 env_file)을 병합하며,
    실제 환경변수를 우선한다. 값은 첫 ":"로만 분리해 등급/호스트경로를
    얻는다(드라이브 문자의 ":"를 보존). 등급이 잘못되면 안전을 위해
    strict로 강등한다.

    Returns:
        {별칭: {"grade", "host", "container"}}
    """
    raw: dict[str, str] = {}

    # 1-1. .env 파일 (로컬 실행 시)
    env_path = Path(".env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            raw[k.strip()] = v.strip()

    # 1-2. 실제 환경변수 우선 (도커)
    for k, v in os.environ.items():
        if k.startswith("FILE_OPS_"):
            raw[k] = v

    areas: dict[str, dict] = {}
    for key, value in raw.items():
        if not key.startswith("FILE_OPS_") or ":" not in value:
            continue
        alias = key[len("FILE_OPS_"):].strip().lower()
        if not alias:
            continue
        grade, host = value.split(":", 1)
        grade = grade.strip().lower()
        host = host.strip().strip('"').strip("'")
        if not host:
            continue
        if grade not in _FILE_OPS_GRADES:
            grade = "strict"
        areas[alias] = {
            "grade": grade,
            "host": host,
            "container": f"{FILE_OPS_CONTAINER_ROOT}/{alias}",
        }
    return areas


FILE_OPS_AREAS = _collect_file_ops_areas()


# ─────────────────────────────────────
# 2. 경로 해석
# ─────────────────────────────────────

# ──────────────────────────
# 2-1. 호스트 경로 조합
# ──────────────────────────
def _host_join(host: str, rel: str) -> str:
    """호스트 표시 경로(윈도우 백슬래시)를 만든다. rel이 비면 host만."""
    host_norm = host.replace("/", "\\").rstrip("\\")
    if not rel:
        return host_norm
    return host_norm + "\\" + rel.replace("/", "\\")


# ──────────────────────────
# 2-2. 컨테이너 경로 빌드
# ──────────────────────────
def _build(alias: str, area: dict, rel: str):
    """rel(영역 상대경로)을 컨테이너 절대경로로 만들고 base 이탈을 차단한다."""
    base = Path(area["container"]).resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        return None
    return alias, target, _host_join(area["host"], rel)


# ─────────────────────
# 2-3. 별칭 확정
# ─────────────────────
def _pick_alias(area: str) -> str | None:
    """
    영역 별칭을 확정한다. 비어 있으면 첫 번째 등록 영역, 미등록이면 None.

    Args:
        area: 영역 별칭 (빈 값 허용)
    Returns:
        확정된 별칭 또는 None
    """
    if area and str(area).strip():
        a = str(area).strip()
        return a if a in FILE_OPS_AREAS else None
    if not FILE_OPS_AREAS:
        return None
    return next(iter(FILE_OPS_AREAS))


# ─────────────────────
# 2-4. 상대경로 정규화
# ─────────────────────
def _norm_rel(alias: str, area: dict, path: str) -> str:
    """
    path를 영역 내 상대경로로 정규화한다.

    모델이 호스트/컨테이너 base나 'alias/' 접두사를 그대로 넣어도 벗겨낸다.

    Args:
        alias: 영역 별칭
        area : 영역 정보
        path : 입력 경로
    Returns:
        영역 내 상대경로
    """
    s = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not s:
        return ""
    bases = (
        area["host"].replace("\\", "/").rstrip("/"),
        area["container"].rstrip("/"),
        alias,
    )
    for base in bases:
        if s == base:
            return ""
        if s.startswith(base + "/"):
            return s[len(base) + 1:].lstrip("/")
    return s


# ─────────────────────
# 2-5. 경로 해석 통합
# ─────────────────────
def _resolve(area: str, path: str):
    """
    (영역 별칭, 영역 내 경로)를 (별칭, 컨테이너 절대경로, 호스트 표시경로)로 해석한다.

    area가 비면 첫 번째 등록 영역을 쓰고, 미등록 별칭이면 거부한다.

    Args:
        area: 영역 별칭 (빈 값 허용)
        path: 영역 내 파일 경로 (파일명 또는 하위경로)
    Returns:
        (alias, container_path, host_display) 또는 None
    """
    alias = _pick_alias(area)
    if alias is None:
        return None
    info = FILE_OPS_AREAS[alias]
    return _build(alias, info, _norm_rel(alias, info, path))


# ─────────────────────────────────────
# 3. 영역 힌트 (SPEC 설명용)
# ─────────────────────────────────────
def _areas_hint() -> str:
    """등록된 영역을 모델용 설명 문구로 만든다."""
    if not FILE_OPS_AREAS:
        return "등록된 영역이 없다."
    parts = [
        f"{a} ({area['host']}, {area['grade']})"
        for a, area in FILE_OPS_AREAS.items()
    ]
    return "등록된 영역 별칭: " + ", ".join(parts)


_AREAS_HINT = _areas_hint()


# ─────────────────────────────────────
# 4. 도구 스펙
# ─────────────────────────────────────
SPEC = {
    "type": "function",
    "function": {
        "name": "file_ops",
        "description": (
            "등록된 영역 안에서 파일을 생성·읽기·나열·수정·삭제·이동·복원한다. "
            "사용자가 파일 작업을 명시적으로 요청할 때만 사용한다. "
            "영역은 area로, 영역 안의 파일 경로는 path로 분리해서 지정한다. "
            + _AREAS_HINT
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "list", "modify", "delete", "purge", "move", "restore"],
                    "description": (
                        "수행할 작업. list는 폴더 내용 나열(휴지통 보려면 path='.trash'). "
                        "delete는 휴지통(.trash)으로 이동해 복구 가능, "
                        "restore는 휴지통에서 원래 이름으로 복원('복구해줘' 요청 시). "
                        "purge는 완전 삭제로 복구 불가('완전히 삭제' 요청 시, 폴더는 하위 포함)."
                    ),
                },
                "area": {
                    "type": "string",
                    "description": (
                        "작업할 영역 별칭. " + _AREAS_HINT
                        + " 비우면 첫 번째 영역을 사용한다."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "영역 내 파일 경로. 파일명 또는 하위경로 (예: test.txt, sub/test.txt).",
                },
                "content": {
                    "type": "string",
                    "description": "파일 내용 (create·modify에서 사용).",
                },
                "dest": {
                    "type": "string",
                    "description": "이동 대상 경로 (move에서 사용). 영역 내 파일 경로 (예: sub/moved.txt).",
                },
                "area_dest": {
                    "type": "string",
                    "description": "이동 대상 영역 별칭 (move에서 사용). 비우면 area와 같은 영역.",
                },
            },
            "required": ["action", "path"],
        },
    },
}


# ─────────────────────────────────────
# 5. confirm 필요 여부
# ─────────────────────────────────────

# ─────────────────────
# 5-1. 등급 판정
# ─────────────────────
def _effective_grade(args: dict) -> str:
    """
    대상 경로(들)의 등급 중 가장 엄격한 등급을 반환한다.

    move는 path·dest 둘 다 고려한다. 해석 불가 경로가 있으면
    안전을 위해 strict로 간주한다.

    Args:
        args: 도구 인자 dict
    Returns:
        "safe" | "normal" | "strict"
    """
    targets = [(args.get("area"), args.get("path"))]
    if args.get("action") == "move":
        targets.append((args.get("area_dest") or args.get("area"), args.get("dest")))

    grades = []
    for area, path in targets:
        r = _resolve(area, path)
        if r is None:
            return "strict"
        grades.append(FILE_OPS_AREAS[r[0]]["grade"])
    if not grades:
        return "strict"
    return max(grades, key=lambda g: _GRADE_RANK.get(g, 2))


# ─────────────────────
# 5-2. confirm 판정
# ─────────────────────
def needs_confirm(args: dict) -> bool:
    """
    영역 등급과 action으로 confirm 필요 여부를 판정한다.

    safe=전부 면제, normal=read/list만 면제, strict=전부 확인.
    purge는 등급 무관 항상 확인 (복구 불가).

    Args:
        args: 도구 인자 dict
    Returns:
        확인이 필요하면 True
    """
    if args.get("action") == "purge":
        return True
    grade = _effective_grade(args)
    if grade == "safe":
        return False
    if grade == "strict":
        return True
    return args.get("action") not in FILE_OPS_SAFE_ACTIONS   # normal


# ─────────────────────────────────────
# 6. 휴지통 경로
# ─────────────────────────────────────
def _to_trash(target: Path) -> Path:
    """대상이 속한 영역의 .trash 하위로 옮길 고유 경로를 만든다."""
    for area in FILE_OPS_AREAS.values():
        base = Path(area["container"]).resolve()
        if target == base or base in target.parents:
            trash_dir = base / ".trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            return trash_dir / f"{target.name}.{uuid.uuid4().hex[:8]}"
    # 폴백 (이론상 도달 안 함 — target은 이미 검증됨)
    trash_dir = Path(FILE_OPS_CONTAINER_ROOT) / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    return trash_dir / f"{target.name}.{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────
# 7. 실행 미리보기
# ─────────────────────────────────────
def preview(args: dict) -> str:
    """
    confirm 전 "이렇게 됩니다"를 부작용 없이 보여준다 (별칭+호스트경로 표시).

    Args:
        args: 도구 인자 dict
    Returns:
        미리보기 문구
    """
    action = args.get("action")
    r = _resolve(args.get("area"), args.get("path"))
    if r is None:
        return f"경로를 인식할 수 없습니다: area={args.get('area') or '?'} path={args.get('path') or ''}"
    alias, target, host_display = r
    name = target.name
    is_root = (target == Path(FILE_OPS_AREAS[alias]["container"]).resolve())

    if action == "create":
        content = (args.get("content") or "").strip()
        if content:
            snippet = content[:50] + ("…" if len(content) > 50 else "")
            return f"{alias} 영역의 {name}를 생성합니다 ({host_display}). 내용은 {snippet}입니다."
        return f"{alias} 영역의 {name}를 생성합니다 ({host_display})."
    if action == "modify":
        return f"{alias} 영역의 {name}를 수정합니다 ({host_display})."
    if action == "delete":
        if is_root:
            return f"{alias} 영역의 모든 내용을 휴지통으로 이동합니다 ({host_display}). 폴더는 유지됩니다."
        return f"{alias} 영역의 {name}를 삭제합니다 ({host_display})."
    if action == "purge":
        if is_root:
            cnt = sum(1 for f in target.rglob("*") if f.is_file())
            return (
                f"{alias} 영역의 모든 내용({cnt}개 파일)을 완전히 삭제합니다. "
                f"폴더는 유지됩니다. 복구할 수 없습니다."
            )
        if target.is_dir():
            cnt = sum(1 for f in target.rglob("*") if f.is_file())
            return (
                f"{alias} 영역의 {name} 폴더와 하위 {cnt}개 파일을 완전히 삭제합니다 "
                f"({host_display}). 복구할 수 없습니다."
            )
        return f"{alias} 영역의 {name}를 완전히 삭제합니다 ({host_display}). 복구할 수 없습니다."
    if action == "read":
        return f"{alias} 영역의 {name}를 읽습니다 ({host_display})."
    if action == "list":
        return f"{alias} 영역의 {name} 폴더 내용을 봅니다 ({host_display})."
    if action == "restore":
        return f"{alias} 영역의 {name}를 휴지통에서 복원합니다 ({host_display})."
    if action == "move":
        rd = _resolve(args.get("area_dest") or args.get("area"), args.get("dest"))
        if rd:
            dalias, dtarget, dhost = rd
            return (
                f"{alias} 영역의 {name}를 {dalias} 영역의 {dtarget.name}로 이동합니다 "
                f"({host_display} → {dhost})."
            )
        return f"{alias} 영역의 {name}를 이동합니다 ({host_display})."
    return f"{alias} 영역의 {name} 작업({action})을 진행합니다 ({host_display})."


# ─────────────────────────────────────
# 8. 도구 실행
# ─────────────────────────────────────
def run(args: dict) -> str:
    """
    action에 따라 파일 작업을 수행한다 (실제 작업은 컨테이너경로, 표시는 호스트경로).

    모든 action은 영역 화이트리스트를 통과해야 하며, 삭제·덮어쓰기는
    원본을 해당 영역 .trash로 보존(롤백 가능)한다.

    Args:
        args: {"action", "area"?, "path", "content"?, "dest"?, "area_dest"?}
    Returns:
        결과 JSON 문자열 (성공별 키 / {"error": ...})
    """
    action = args.get("action")
    if action not in FILE_OPS_ACTIONS:
        return err(f"알 수 없는 작업입니다: {action}")

    r = _resolve(args.get("area"), args.get("path"))
    if r is None:
        return err("허용되지 않은 영역/경로입니다.")
    alias, p, host_display = r

    try:
        # ──────────────────────────────────────
        # 8-1. read — 내용 반환
        # ──────────────────────────────────────
        if action == "read":
            if not p.is_file():
                return err("파일이 없습니다.")
            with p.open("r", encoding="utf-8", errors="replace") as f:
                text = f.read(FILE_OPS_READ_MAX_CHARS + 1)
            truncated = len(text) > FILE_OPS_READ_MAX_CHARS
            text = text[:FILE_OPS_READ_MAX_CHARS]
            return ok(content=text, path=host_display, truncated=truncated)

        # ──────────────────────────────────────
        # 8-2. list — 폴더 내용 나열
        # ──────────────────────────────────────
        if action == "list":
            if not p.exists():
                return err("경로가 없습니다.")
            if not p.is_dir():
                return err("폴더가 아닙니다.")
            entries = []
            for child in sorted(p.iterdir()):
                if child.is_dir():
                    entries.append({"name": child.name, "type": "dir"})
                else:
                    entries.append({
                        "name": child.name, "type": "file",
                        "size": child.stat().st_size,
                    })
                if len(entries) >= FILE_OPS_LIST_MAX:
                    break
            return ok(path=host_display, entries=entries)

        # ──────────────────────────────────────
        # 8-3. create — 신규 생성
        # ──────────────────────────────────────
        if action == "create":
            if p.exists():
                return err("이미 존재합니다. 수정하려면 modify를 사용하세요.")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content") or "", encoding="utf-8")
            logger.debug("파일 생성: %s", p)
            return ok(created=True, path=host_display)

        # ──────────────────────────────────────
        # 8-4. modify — 덮어쓰기 (원본 백업)
        # ──────────────────────────────────────
        if action == "modify":
            if not p.is_file():
                return err("수정할 파일이 없습니다. 생성하려면 create를 사용하세요.")
            shutil.move(str(p), str(_to_trash(p)))
            p.write_text(args.get("content") or "", encoding="utf-8")
            logger.debug("파일 수정(백업): %s", p)
            return ok(modified=True, path=host_display, backup=True)

        # ──────────────────────────────────────
        # 8-5. delete — 휴지통 이동
        # ──────────────────────────────────────
        if action == "delete":
            if not p.exists():
                return err("파일이 없습니다.")
            if p == Path(FILE_OPS_AREAS[alias]["container"]).resolve():
                # 루트: 폴더는 유지하고 안의 내용만 휴지통으로 이동 (.trash 제외)
                moved = 0
                for child in list(p.iterdir()):
                    if child.name == ".trash":
                        continue
                    shutil.move(str(child), str(_to_trash(child)))
                    moved += 1
                logger.debug("영역 루트 비우기(휴지통 이동): %s (%d개)", p, moved)
                return ok(deleted=True, path=host_display, backup=True, count=moved)
            shutil.move(str(p), str(_to_trash(p)))
            logger.debug("파일 삭제(휴지통 이동): %s", p)
            return ok(deleted=True, path=host_display, backup=True)

        # ──────────────────────────────────────
        # 8-6. purge — 완전 삭제
        # ──────────────────────────────────────
        if action == "purge":
            if not p.exists():
                return err("대상이 없습니다.")
            if p == Path(FILE_OPS_AREAS[alias]["container"]).resolve():
                # 루트: 폴더는 유지하고 안의 모든 내용 완전 삭제 (.trash 포함)
                removed = 0
                for child in list(p.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    removed += 1
                logger.debug("영역 루트 비우기(완전 삭제): %s (%d개)", p, removed)
                return ok(purged=True, path=host_display, count=removed)
            if p.is_dir():
                shutil.rmtree(p)
                logger.debug("폴더 완전 삭제: %s", p)
            else:
                p.unlink()
                logger.debug("파일 완전 삭제: %s", p)
            return ok(purged=True, path=host_display)

        # ──────────────────────────────────────
        # 8-7. move — 이동 (dest 기존 파일 백업)
        # ──────────────────────────────────────
        if action == "move":
            rd = _resolve(args.get("area_dest") or args.get("area"), args.get("dest"))
            if rd is None:
                return err("이동 대상(dest) 영역/경로가 없거나 허용되지 않았습니다.")
            _, dest, dest_host = rd
            if not p.exists():
                return err("이동할 파일이 없습니다.")

            backed_up = False
            if dest.exists():
                shutil.move(str(dest), str(_to_trash(dest)))
                backed_up = True
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            logger.debug("파일 이동: %s → %s (백업=%s)", p, dest, backed_up)
            return ok(moved=True, src=host_display, dest=dest_host, backup=backed_up)

        # ──────────────────────────────────────
        # 8-8. restore — 휴지통 복원
        # ──────────────────────────────────────
        if action == "restore":
            if p.exists():
                return err("같은 이름의 파일이 이미 있습니다.")
            trash_dir = Path(FILE_OPS_AREAS[alias]["container"]).resolve() / ".trash"
            if not trash_dir.is_dir():
                return err("휴지통이 없습니다.")
            # 삭제 시 {원본명}.{hex}로 보관되므로 접두사로 최신본을 찾는다
            matches = sorted(
                trash_dir.glob(f"{p.name}.*"),
                key=lambda f: f.stat().st_mtime, reverse=True,
            )
            if not matches:
                return err("휴지통에서 해당 파일을 찾을 수 없습니다.")
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(matches[0]), str(p))
            logger.debug("복원: %s ← %s", p, matches[0].name)
            return ok(restored=True, path=host_display)

    except Exception as e:
        logger.warning("파일 작업 실패: %s — %s", action, e)
        return err("파일 작업 중 오류가 발생했습니다.")


# ─────────────────────────────────────
# 9. 도구 안내 문구
# ─────────────────────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    labels = {
        "create": "파일 생성",
        "read": "파일 읽기",
        "list": "파일 목록",
        "modify": "파일 수정",
        "delete": "파일 삭제",
        "purge": "완전 삭제",
        "move": "파일 이동",
        "restore": "복원",
    }
    label = labels.get(args.get("action", ""), "파일 작업")
    return (f"{label} 중...", f"{label}을 진행하겠습니다.")