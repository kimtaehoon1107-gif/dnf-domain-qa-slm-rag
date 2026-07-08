from __future__ import annotations

from dataclasses import dataclass


INTENT_KEYWORDS = {
    "patch_note": ["패치", "업데이트", "변경", "밸런스", "후딜레이"],
    "notice": ["점검", "공지", "클라이언트", "보상"],
    "event": ["이벤트", "코인", "핫타임", "길드", "복귀"],
    "game_system": ["장비", "성장", "명성", "경매장", "엠블렘", "던전"],
    "character_item": ["소환사", "남레인저", "마법사", "프리스트", "탈리스만", "스킬"],
    "operation_policy": ["제재", "복구", "신고", "거래 제한", "비인가", "정책"],
    "account_payment": ["계정", "OTP", "환불", "결제", "보안", "잠금"],
    "bug_known_issue": ["오류", "버그", "지연", "수정", "문제"],
    "recommendation": ["추천", "뭐부터", "제일", "최종", "우선순위"],
}

PERSONAL_OR_REALTIME_KEYWORDS = [
    "내 계정",
    "제 계정",
    "내 캐릭터",
    "지금 장애",
    "현재 장애",
]

WEAK_EVIDENCE_DISTANCE_THRESHOLD = 0.75


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def contains_all(text: str, keywords: list[str]) -> bool:
    return all(keyword in text for keyword in keywords)


def is_unanswerable_request(question: str) -> bool:
    question = question.lower()
    if contains_any(question, PERSONAL_OR_REALTIME_KEYWORDS):
        return True
    # Prompt injection: "ignore prior instructions" phrased many ways
    # ("이전 지시는 모두 무시", "지금까지 지시사항은 무시하고", ...).
    if contains_any(question, ["시스템 프롬프트", "내부 평가 기준"]):
        return True
    if contains_all(question, ["지시", "무시"]):
        return True
    # Prompt/rule leakage: asking to expose internal rules/criteria.
    if contains_all(question, ["내부", "기준"]) or contains_all(question, ["내부", "규칙"]):
        return True
    if "공식 문서에 없는" in question or "문서에 없" in question or "예측" in question or "예상해서" in question:
        return True
    if contains_any(question, ["문서와 상관없는", "상관없는 주식", "주식 종목"]) or contains_all(
        question, ["상관없", "주식"]
    ) or "주식" in question:
        return True
    if contains_all(question, ["순위", "최종"]) or contains_all(question, ["순위", "최강"]):
        return True
    if "날씨" in question:
        return True
    if "시세" in question and contains_any(question, ["지금", "현재", "실시간", "오늘"]):
        return True
    # Reward/exploit abuse: literal "악용"/"반복해서 받" or paraphrases like
    # "여러 번 반복" + "받"/"편법".
    if "악용" in question or "반복해서 받" in question or "편법" in question:
        return True
    if contains_all(question, ["반복", "받"]):
        return True
    if "버그" in question and contains_any(question, ["단계별", "방법"]):
        return True
    # Unsupported reward confirmation: "확실히/확정 받을 수 있다고 딱 잘라/확정해서 말해줘".
    if contains_any(question, ["딱 잘라 말해", "확정해서 답해", "확정해서 말해"]):
        return True
    return False


@dataclass
class GroundedResponse:
    intent: str
    answerability: str
    answer: str
    evidence: list[str]
    caution: str

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "answerability": self.answerability,
            "answer": self.answer,
            "evidence": self.evidence,
            "caution": self.caution,
        }


def infer_intent(question: str, contexts: list[dict]) -> str:
    if contexts:
        top_doc_type = contexts[0].get("doc_type")
        if top_doc_type in INTENT_KEYWORDS:
            return top_doc_type

    scores = {
        intent: sum(1 for keyword in keywords if keyword.lower() in question.lower())
        for intent, keywords in INTENT_KEYWORDS.items()
    }
    best_intent, best_score = max(scores.items(), key=lambda item: item[1])
    return best_intent if best_score > 0 else "unknown"


def judge_answerability(question: str, contexts: list[dict]) -> str:
    if is_unanswerable_request(question):
        return "false"
    if not contexts:
        return "false"
    partial_request_keywords = [
        "추천해",
        "추천 좀",
        "우선순위",
        "확정",
        "무조건",
        "가장 좋은",
        "뭐부터",
    ]
    if contains_any(question, partial_request_keywords):
        return "partial"

    # Use the closest evidence (min distance) rather than contexts[0], whose
    # order is decided by the blended retrieval score, not raw similarity.
    distances = [
        context["distance"]
        for context in contexts
        if isinstance(context.get("distance"), (int, float))
    ]
    if distances and min(distances) > WEAK_EVIDENCE_DISTANCE_THRESHOLD:
        return "false"
    return "true"


def build_grounded_answer(question: str, contexts: list[dict]) -> GroundedResponse:
    intent = infer_intent(question, contexts)
    answerability = judge_answerability(question, contexts)
    caution = "이 답변은 수집된 문서와 검색 결과 기준입니다."

    if answerability == "false":
        return GroundedResponse(
            intent=intent,
            answerability=answerability,
            answer="수집된 문서만으로는 질문에 답하기에 충분한 근거가 없습니다.",
            evidence=[],
            caution=caution,
        )

    top_context = contexts[0]
    body = top_context["text"].replace("\n\n", " ")
    if len(body) > 360:
        body = body[:360].rstrip() + "..."

    return GroundedResponse(
        intent=intent,
        answerability=answerability,
        answer=body,
        evidence=[top_context["doc_id"]],
        caution=caution,
    )
