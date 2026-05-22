from dataclasses import dataclass


@dataclass(frozen=True)
class Reviewer:
    github_id: str
    nickname: str


REVIEWERS = (
    Reviewer("Gyuchool", "기론"),
    Reviewer("younghoondoodoom", "두둠"),
    Reviewer("robinjoon", "로빈"),
    Reviewer("Rok93", "로키"),
    Reviewer("hyeonic", "매트"),
    Reviewer("Arachneee", "백호"),
    Reviewer("verus-j", "베루스"),
    Reviewer("pci2676", "비밥"),
    Reviewer("her0807", "수달"),
    Reviewer("syoun602", "썬"),
    Reviewer("donghoony", "아루"),
    Reviewer("NewWisdom", "아마찌"),
    Reviewer("Hyunta", "아서"),
    Reviewer("echo724", "에코"),
    Reviewer("choijy1705", "영이"),
    Reviewer("sihyung92", "웨지"),
    Reviewer("yenawee", "제나"),
    Reviewer("jamie9504", "제이미"),
    Reviewer("Choi-JJunho", "주노"),
    Reviewer("jurlring", "주디"),
    Reviewer("Gomding", "찰리"),
    Reviewer("Chocochip101", "초코칩"),
    Reviewer("include42", "카프카"),
    Reviewer("pkeugine", "피케이"),
)

REVIEWER_NICKNAMES_BY_ID = {reviewer.github_id.lower(): reviewer.nickname for reviewer in REVIEWERS}
REVIEWER_GITHUB_IDS = frozenset(REVIEWER_NICKNAMES_BY_ID)


def is_reviewer(github_id: str | None) -> bool:
    if not github_id:
        return False
    return github_id.lower() in REVIEWER_GITHUB_IDS


def reviewer_nickname(github_id: str) -> str | None:
    return REVIEWER_NICKNAMES_BY_ID.get(github_id.lower())
