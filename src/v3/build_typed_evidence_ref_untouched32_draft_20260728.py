from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.v3 import build_typed_evidence_ref_unexecuted32_draft as base


requirement = base.requirement
case = base.case


SPECS = [
    # dnf_notice
    case(
        "dnf_notice",
        "temporal_role",
        "document_sha256_311577f37d817b7512405e92f17dd32da8a9b5ad6260965ab36882b8038faeaf",
        "7월 8일 퍼스트 서버는 원래 몇 시 오픈 예정이었고, 실제로 몇 시로 지연됐어?",
        [
            requirement(
                "scheduled_open_at",
                "7월 8일 퍼스트 서버",
                "scheduled_open_at",
                "time",
                ["15:00"],
                ["▣ 퍼스트 서버 오픈 지연 - 15:00 → 15:10"],
            ),
            requirement(
                "delayed_open_at",
                "7월 8일 퍼스트 서버",
                "delayed_open_at",
                "time",
                ["15:10"],
                ["▣ 퍼스트 서버 오픈 지연 - 15:00 → 15:10"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "boolean_direction",
        "document_sha256_c846decea5e3210725c961161ea85c9f922b8bcf51f68445eefb51c0851ac793",
        "2026년 7월 2일 공지 시점에 DirectX 9 지원은 이미 종료된 상태였어?",
        [
            requirement(
                "support_already_ended",
                "DirectX 9 지원",
                "support_already_ended",
                "boolean",
                [False],
                ["이러한 안정화 추이를 바탕으로 향후 DirectX 9 지원 종료를 검토하고 있음을 안내드리며,"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "multi_requirement",
        "document_sha256_488b3fc9e3dc578bad12aaf8a937e5ecc698832188f2cedc0ddfea04399ffef1",
        "Npay 7% 적립 이벤트의 최소 충전금액, 적립률, 최대 적립액은 각각 얼마였어?",
        [
            requirement(
                "minimum_charge",
                "Npay 7% 적립 이벤트",
                "minimum_charge",
                "currency",
                [{"amount": 40000, "unit": "원"}],
                ["■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)"],
            ),
            requirement(
                "accrual_rate",
                "Npay 7% 적립 이벤트",
                "accrual_rate",
                "percentage",
                [7],
                ["■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)"],
            ),
            requirement(
                "maximum_accrual",
                "Npay 7% 적립 이벤트",
                "maximum_accrual",
                "currency",
                [{"amount": 4000, "unit": "원"}],
                ["■ 이벤트 내용 : Npay로 4만원 이상 충전 시 7% 네이버페이 포인트 적립 (최대 4,000원, 중복 불가, 네이버페이 실명 인증 기준 1인 1회 참여 가능)"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_notice",
        "unsupported_or_partial",
        "document_sha256_cedffb9e8861a96d80c1e7d2a1026925fb074264e8d4079ede49c666037272dd",
        "2026년 7월 17일 넥슨 고객상담실 방문 상담은 가능했는지와 전화 상담 운영시간을 알려줘.",
        [
            requirement(
                "visit_available",
                "2026년 7월 17일 넥슨 고객상담실",
                "visit_available",
                "boolean",
                [False],
                ["7/17(금)에는 방문 상담 서비스를 이용하실 수 없습니다."],
            ),
            requirement(
                "telephone_hours",
                "2026년 7월 17일 넥슨 고객상담실",
                "telephone_hours",
                "text",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        time_scope="historical",
        expected_response_mode="partial_answer",
    ),
    # dnf_update
    case(
        "dnf_update",
        "direct_fact",
        "document_sha256_ebb2d07a700b1461b3bb3bf246a5428d82d533e91b58f211a7127d5ee7d46a01",
        "5월 6일 퍼스트 서버 업데이트 기준 최후의 과업 채널 입장 명성은 얼마였어?",
        [
            requirement(
                "entry_fame",
                "최후의 과업 채널",
                "entry_fame",
                "number",
                [108921],
                ["<최후의 과업> 채널은 모험가 명성 108,921부터 입장이 가능합니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "sibling_relation",
        "document_sha256_02c3b128896e1e3040f725af3ad4831e517a42efb2a5dfbde6bea828efd7f78c",
        "7월 16일 캐릭터 밸런스 패치에서 그래플러(남)와 넨마스터(여)의 스킬 공격력 증가율은 각각 얼마였어?",
        [
            requirement(
                "male_grappler_attack_increase",
                "그래플러(남)",
                "attack_increase",
                "percentage",
                [12.3],
                ["## 그래플러(남)\n기본 공격 및 전직 계열 스킬 공격력이 12.3% 증가합니다."],
            ),
            requirement(
                "female_nenmaster_attack_increase",
                "넨마스터(여)",
                "attack_increase",
                "percentage",
                [8.8],
                ["## 넨마스터(여)\n기본 공격 및 전직 계열 스킬 공격력이 8.8% 증가합니다."],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "table_attribute",
        "document_sha256_ebb2d07a700b1461b3bb3bf246a5428d82d533e91b58f211a7127d5ee7d46a01",
        "5월 6일 퍼스트 서버 업데이트의 최후의 과업 모험도감 ★10 보상과 거래 타입은 뭐였어?",
        [
            requirement(
                "reward",
                "최후의 과업 모험도감 ★10",
                "reward",
                "entity",
                ["신야 대두 아바타 상자"],
                ["| ★10 | 신야 대두 아바타 상자 | 계정귀속 |"],
            ),
            requirement(
                "trade_type",
                "최후의 과업 모험도감 ★10",
                "trade_type",
                "enum",
                ["계정귀속"],
                ["| ★10 | 신야 대두 아바타 상자 | 계정귀속 |"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_update",
        "revision_selection",
        "document_sha256_ebb2d07a700b1461b3bb3bf246a5428d82d533e91b58f211a7127d5ee7d46a01",
        "5월 6일 퍼스트 서버 업데이트 기준 최후의 과업 주간 입장 제한과 통합 보상 횟수는 각각 몇 회였어?",
        [
            requirement(
                "weekly_entry_limit",
                "최후의 과업",
                "weekly_entry_limit",
                "number",
                [1],
                ["| 주간 입장 제한 | 1회 콘텐츠 시작 시 주간 입장 제한 횟수가 차감됩니다. |"],
            ),
            requirement(
                "integrated_reward_count",
                "최후의 과업",
                "integrated_reward_count",
                "number",
                [2],
                ["| 통합 보상 횟수 | 2회 제한 시간 내 콘텐츠 클리어 시 주간 보상을 획득하실 수 있습니다. 보상 획득 시 통합 보상 횟수는 차감됩니다. 주간 입장 제한 및 통합 보상 횟수는 매주 목요일 06시에 초기화됩니다. |"],
            ),
        ],
        time_scope="historical",
    ),
    # dnf_event
    case(
        "dnf_event",
        "direct_fact",
        "document_sha256_cc205a8439b2f921ecebce31ac1cb0e8691894ec13f44da7b4a95b6a39a95d18",
        "레바vs낡은창고 드로잉쇼 쿠폰은 계정당 몇 번 입력할 수 있었어?",
        [
            requirement(
                "coupon_input_limit",
                "레바vs낡은창고 드로잉쇼 쿠폰",
                "coupon_input_limit",
                "number",
                [1],
                ["- 모든 쿠폰은 계정당 1회 입력 가능합니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_event",
        "temporal_role",
        "document_sha256_39da28f9916af1dda35dc7657f7db382d0524ccef2b91677859d1898334a2638",
        "파도치는 폭권으로! 보급 작전 이벤트 기간은 언제부터 언제까지였어?",
        [
            requirement(
                "event_period",
                "파도치는 폭권으로! 보급 작전",
                "event_period",
                "date_range",
                ["2026-07-02", "2026-07-23"],
                ["# 파도치는 폭권으로! 보급 작전 | 이벤트 기간 : 2026년 7월 2일(목) 점검 후 ~ 7월 23일(목) 점검 전"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_event",
        "multi_requirement",
        "document_sha256_d59f3c4278301e5fe7a5a25fa132c9295f4eb699be7a8ef6c0067f7b84b31a87",
        "여름맞이 7일간의 여정 이벤트의 하루 기준(초기화 시각)과 보상 우편 보관 기간은 각각 며칠/몇 시야?",
        [
            requirement(
                "daily_boundary_at",
                "여름맞이 7일간의 여정",
                "daily_boundary_at",
                "text",
                ["매일 오전 06시 - 다음날 오전 06시"],
                ["본 이벤트의 하루 기준은 매일 오전 06시 - 다음날 오전 06시입니다."],
            ),
            requirement(
                "mail_retention_days",
                "여름맞이 7일간의 여정 보상",
                "mail_retention_days",
                "number",
                [15],
                ["게임 접속 후 [보상받기]를 클릭하면 보상을 받을 수 있으며, 지급된 보상은 우편함에서 확인 가능합니다. (우편 보관 기간: 15일)"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_event",
        "boolean_direction",
        "document_sha256_d101696874e336a8628e6fe0b03ca9b906d0c03bf71c562d4e0a80058794459d",
        "트리니티 이벤트의 일반모드 플레이도 랭킹 집계에 포함됐어?",
        [
            requirement(
                "normal_mode_counted",
                "트리니티 일반모드",
                "ranked",
                "boolean",
                [False],
                ["- 랭킹은 챌린지모드 3종의 몬스터를 모두 처치 시에만 집계 합니다. (일반모드는 랭킹 집계와 무관합니다.)"],
            )
        ],
        time_scope="historical",
    ),
    # dnf_faq
    case(
        "dnf_faq",
        "boolean_direction",
        "document_sha256_55db71f74dbf354031a4e88c4aa046db73ffdf47fbb6658b362a6cdbec5e0c5c",
        "성장 가속 모드 상태의 캐릭터로 결투장을 이용할 수 있어?",
        [
            requirement(
                "duel_arena_available",
                "성장 가속 모드 캐릭터",
                "duel_arena_available",
                "boolean",
                [False],
                ["아쉽게도 성장 가속 모드 상태에서는 결투장 이용이 어렵습니다."],
            )
        ],
    ),
    case(
        "dnf_faq",
        "direct_fact",
        "document_sha256_e741bbc715e6ce9f458105b80e631053452b51a4c3185de505d4391a3c1a6ba8",
        "세라 충전한도는 마이페이지에서 어떤 경로로 변경할 수 있어?",
        [
            requirement(
                "settings_path",
                "세라 충전한도",
                "settings_path",
                "text",
                ["마이페이지 → 세라 관리 → 세라 충전한도 설정 및 확인"],
                ["위 링크 또는 (마이페이지 → 세라 관리 → 세라 충전한도 설정 및 확인)에서 확인하실 수 있습니다."],
            )
        ],
    ),
    case(
        "dnf_faq",
        "sibling_relation",
        "document_sha256_80444aa366c6eed2ef7b4cd1a2560fb256ca9f4045d2c50f29039d5c37681bfd",
        "네오플OTP 에러 코드 22를 해결할 때 재설치 후 안드로이드와 iOS에서 각각 어떤 시간 설정을 해야 해?",
        [
            requirement(
                "android_time_setting",
                "네오플OTP 에러 코드 22 안드로이드",
                "time_sync_setting",
                "text",
                ["OTP 실행 → 좌측 상단 버튼 누른 후 시간설정 → 시간 동기화"],
                ["⑥ (재설치 후) OTP 실행 → 좌측 상단 버튼 누른 후 시간설정 → 시간 동기화"],
            ),
            requirement(
                "ios_time_setting",
                "네오플OTP 에러 코드 22 iOS",
                "time_sync_setting",
                "text",
                ["설정 → 일반 → 날짜와시간 → 자동으로 설정 체크"],
                ["⑥ (재설치 후) 설정 → 일반 → 날짜와시간 → 자동으로 설정 체크"],
            ),
        ],
    ),
    case(
        "dnf_faq",
        "unsupported_or_partial",
        "document_sha256_c34a68bcfcb60be16de99b820cf89a6f3983c241694beba4b5e72cbc1ac037e7",
        "장착 칭호가 해제되지 않을 때 1:1 문의에 적어야 할 정보와 평균 처리 기간을 알려줘.",
        [
            requirement(
                "required_inquiry_fields",
                "장착 칭호 해제 1:1 문의",
                "required_inquiry_fields",
                "entity_list",
                ["서버", "캐릭터명", "장착중인 칭호"],
                ["[기재사항]\n1. 서버/캐릭터명 :\n2. 장착중인 칭호 :"],
            ),
            requirement(
                "average_processing_time",
                "장착 칭호 해제 1:1 문의",
                "average_processing_time",
                "text",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        expected_response_mode="partial_answer",
    ),
    # dnf_game_guide
    case(
        "dnf_game_guide",
        "direct_fact",
        "document_sha256_205145926c9099909656af62a5a2d894148c3605936f795af9b150276da623f0",
        "위업의 기억에서 캐릭터 귀속은 매월 언제 해제돼?",
        [
            requirement(
                "binding_reset_at",
                "위업의 기억 캐릭터 귀속",
                "binding_reset_at",
                "text",
                ["매월 1일 오전 06시"],
                ["| 월간 초기화 | 매월 1일 오전 06시에 캐릭터 귀속 해제 매 달 모든 캐릭터는 다음 달 1티어로 조정 입장 명성 달성 시 이전 클리어 기록과 상관 없이 입장 가능 |"],
            )
        ],
    ),
    case(
        "dnf_game_guide",
        "table_attribute",
        "document_sha256_6b70826ab9c99482b9c4a4b926aa06e003e4293d93f39c3772d1d835e3d72383",
        "광휘의 순례 배니부 상점의 유니크 아티팩트 레시피 거래 속성은 뭐야?",
        [
            requirement(
                "trade_type",
                "광휘의 순례 배니부 상점 유니크 아티팩트 레시피",
                "trade_type",
                "enum",
                ["계정귀속"],
                ["| 유니크 아티팩트 레시피 | 아이템명에 해당하는 유니크 아티팩트를 100% 확률로 제작합니다. 제작된 아이템은 밀봉 상태로 제공됩니다. | 계정귀속 |"],
            )
        ],
    ),
    case(
        "dnf_game_guide",
        "multi_requirement",
        "document_sha256_b75a7695f5281b9b055164e3fad3434df98e9b1650e20afe3b1fd8743b9e65fc",
        "금고 재료 사용 기능은 상점에서 어떻게 켜고, 재료는 어느 두 금고에 있어도 사용할 수 있어?",
        [
            requirement(
                "activation_method",
                "금고 재료 사용 기능",
                "activation_method",
                "text",
                ["상점 메뉴에서 '구매 시, 금고 재료 사용'을 클릭하여 활성화"],
                ["상점 메뉴에서 '구매 시, 금고 재료 사용'을 클릭하여 활성화 합니다."],
            ),
            requirement(
                "supported_vaults",
                "금고 재료 사용 기능",
                "supported_vaults",
                "entity_list",
                ["내 금고", "계정 금고"],
                ["내 금고나 계정 금고에 아이템이 보관되어 있는 경우, 구매 시도 시 재료 사용 동의 메뉴가 등장합니다."],
            ),
        ],
    ),
    case(
        "dnf_game_guide",
        "sibling_relation",
        "document_sha256_88867a7a23e9d5b4abbb173290b6e9771c6bdf8535b8edeab0d6b2f7bc36edaa",
        "칼레이도 박스와 마스터 칼레이도 박스는 장비 품질을 각각 어떻게 바꿔?",
        [
            requirement(
                "regular_quality_result",
                "칼레이도 박스",
                "quality_result",
                "text",
                ["최하급에서 최상급 사이로 랜덤"],
                ["칼레이도 박스를 사용하면 장비 아이템 품질을 최하급에서 최상급 사이로 랜덤하게 설정할 수 있습니다."],
            ),
            requirement(
                "master_quality_result",
                "마스터 칼레이도 박스",
                "quality_result",
                "percentage",
                [100],
                ["마스터 칼레이도 박스를 사용할 경우, 확정적으로 아이템 품질을 100%로 변환할 수 있습니다."],
            ),
        ],
    ),
    # dnf_account_policy
    case(
        "dnf_account_policy",
        "revision_selection",
        "document_sha256_a2d3014dcc9484cde7a3a5e8997205b6243289ef8c756678572ead2404b47d4b",
        "2023년 6월 10일 시행 운영정책에서 휴면ID 전환 기준은 몇 개월 미접속이었어?",
        [
            requirement(
                "inactive_months",
                "2023년 6월 10일 시행 운영정책 휴면ID",
                "inactive_months",
                "number",
                [12],
                ["① 12개월 이상 접속 기록이 없는 경우 휴면ID로 전환하여 관리됩니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_account_policy",
        "boolean_direction",
        "document_sha256_ac04e050a4b437ef4c2e2e94f64ded98cceff391e21938f94a396aaae3250599",
        "2022년 8월 4일 시행 운영정책에서는 비정상 재화를 받은 사람이 고의나 인지 여부와 무관하게 재화를 회수할 수 있었어?",
        [
            requirement(
                "recoverable_regardless_of_awareness",
                "2022년 8월 4일 시행 운영정책 비정상 재화",
                "recoverable_regardless_of_awareness",
                "boolean",
                [True],
                ["[4-4-3] 버그, 시스템 취약점 공격, 비인가 프로그램 사용, 계정도용 등 비정상적으로 생성되거나 이동된 재화(이하 “비정상 재화”)는 고의 여부, 인지 여부와 상관없이 회수됩니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_account_policy",
        "sibling_relation",
        "document_sha256_8ceab3e34629567d1a751d89f1dfad6cf5b504e2fc58ed41262437189a1527cd",
        "2021년 1월 21일 시행 운영정책에서 운영자·직원 사칭과 허위사실 유포의 1차 이용제한은 각각 며칠이었어?",
        [
            requirement(
                "impersonation_first_penalty",
                "운영자·직원 사칭",
                "first_penalty",
                "duration",
                [{"amount": 100, "unit": "일"}],
                ["| 운영자 / 직원을 사칭하는 행위 | 계정100일 이용제한 | 계정1년 이용제한 | 계정3년 이용제한 | 계정영구 이용제한 |"],
            ),
            requirement(
                "false_information_first_penalty",
                "허위사실 유포·제보",
                "first_penalty",
                "duration",
                [{"amount": 10, "unit": "일"}],
                ["| 허위사실 유포, 제보 | 계정10일 이용제한 | 계정30일 이용제한 | 계정100일 이용제한 | 계정영구 이용제한 |"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_account_policy",
        "unsupported_or_partial",
        "document_sha256_246eb602b4d2b9ec051e841f29b5b64db9e155ab4742f08936564fad4942651d",
        "2020년 12월 4일 시행 운영정책에서 길드장 권한이 위임될 수 있는 조건과 처리 기간을 알려줘.",
        [
            requirement(
                "delegation_conditions",
                "길드장 권한 위임",
                "delegation_conditions",
                "entity_list",
                ["길드장 계정이 이용제한 상태", "길드장 계정이 12개월 이상 미접속으로 인한 휴면 상태"],
                ["길드장 임의 교체는 가능하지 않습니다. 단, 아래의 사유에 해당할 경우에는 길드장 권한이 다른 길드원에게 위임될 수 있습니다.\n① 길드장 계정이 이용제한 상태인 경우\n② 길드장 계정이 12개월이상 미접속으로 인한 휴면 상태인 경우"],
            ),
            requirement(
                "processing_time",
                "길드장 권한 위임",
                "processing_time",
                "duration",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        time_scope="historical",
        expected_response_mode="partial_answer",
    ),
    # dnf_seria_shop
    case(
        "dnf_seria_shop",
        "table_attribute",
        "document_sha256_36d8bd6b5e6299b9b2afb7abf04e0603e73d435743987bfeeeaac5474bd3013a",
        "마일리지샵 2026 시즌4의 향상된 럭키 박스 3단계 가격, 구매 조건, 거래 타입은 뭐였어?",
        [
            requirement(
                "price",
                "향상된 럭키 박스 3단계",
                "price",
                "currency",
                [{"amount": 150, "unit": "M"}],
                ["| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |\n| 아이콘 | | | |\n| 가격 | 100M | 120M | 150M |\n| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |\n| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |"],
            ),
            requirement(
                "purchase_condition",
                "향상된 럭키 박스 3단계",
                "purchase_condition",
                "text",
                ["하루 1개 구매 가능, 2단계 구매 후 구매 가능"],
                ["| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |\n| 아이콘 | | | |\n| 가격 | 100M | 120M | 150M |\n| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |\n| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |"],
            ),
            requirement(
                "trade_type",
                "향상된 럭키 박스 3단계",
                "trade_type",
                "enum",
                ["계정귀속"],
                ["| 아이템명 | [M] 향상된 럭키 박스 (1 단계 ) | [M] 향상된 럭키 박스 (2 단계 ) | [M] 향상된 럭키 박스 (3 단계 ) |\n| 아이콘 | | | |\n| 가격 | 100M | 120M | 150M |\n| 구매제한 | 하루 1 개 구매 가능 | 하루 1 개 구매 가능 1 단계 구매 후 구매 가능 | 하루 1 개 구매 가능 2 단계 구매 후 구매 가능 |\n| 거래타입 | 계정귀속 | 계정귀속 | 계정귀속 |"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_seria_shop",
        "temporal_role",
        "document_sha256_38f2599b2f08b91fa006b2cf1aababe79b138043206104e4ac06893fc2e615d2",
        "2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자의 판매 기간과 일괄 삭제 시각은 언제였어?",
        [
            requirement(
                "sale_period",
                "2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자",
                "sale_period",
                "date_range",
                ["2026-04-09", "2026-06-04"],
                ["- 2026 년 04 월 09 일 점검 후부터 2026 년 06 월 04일 점검 전까지 세라샵 > 패키지 > 전체 카테고리에서 만나보실 수 있습니다 ."],
            ),
            requirement(
                "deletion_at",
                "2026 아라드패스 꿈 속의 던토피아 아바타 콤보 상자 및 구성품",
                "deletion_at",
                "datetime",
                ["2026-06-04T06:00:00+09:00"],
                ["- 2026 아라드 패스 꿈 속의 던토피아 아바타 콤보 상자 및 구성 품은 2026년 06월 04일 06시 일괄 삭제됩니다."],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_seria_shop",
        "multi_requirement",
        "document_sha256_1cb39a49ac1f7fa456bb57dc51d3ef9e3c5b9d9e137054a5d3d5e2e3d9413dc5",
        "2026 DNF 폴리스 아바타 콤보 상자의 가격과 구매 시 받는 두 상자는 뭐였어?",
        [
            requirement(
                "price",
                "2026 DNF 폴리스 아바타 콤보 상자",
                "price",
                "currency",
                [{"amount": 12900, "unit": "세라"}],
                ["- 교환가능 아이템 : 12,900 세라"],
            ),
            requirement(
                "included_boxes",
                "2026 DNF 폴리스 아바타 콤보 상자",
                "included_boxes",
                "entity_list",
                ["2026 DNF 폴리스 아바타 풀세트 상자", "2026 DNF 폴리스 보너스 상자"],
                ["- 아바타 콤보 상자 구매 시 , 2026 DNF 폴리스 아바타 풀세트 상자 와 2026 DNF 폴리스 보너스 상자 를 얻을 수 있습니다."],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_seria_shop",
        "revision_selection",
        "document_sha256_06c565de28c5644374faf5bc29fda19ebb457b7c3d2b57f266e797490a28f130",
        "2026년 1월 해방의 열쇠 100개 상자의 판매 기간과, 상자에서 나온 해방의 열쇠 거래 타입은 뭐였어?",
        [
            requirement(
                "sale_period",
                "2026년 1월 해방의 열쇠 100개 상자",
                "sale_period",
                "date_range",
                ["2026-01-01", "2026-01-15"],
                ["26년 1월 1일 00시 ~ 1월 15일 점검 전 까지 판매하는 해방의 열쇠 100개 상자 소개와 함께 주의사항을 안내 드리겠습니다."],
            ),
            requirement(
                "key_trade_type",
                "2026년 1월 해방의 열쇠 100개 상자에서 획득한 해방의 열쇠",
                "trade_type",
                "enum",
                ["교환불가"],
                ["| 툴팁 | 사용 시 해방의 열쇠 100개, 봉인된 자물쇠 34개를 획득할 수 있습니다. 해방의 열쇠는 교환불가, 기간 무제한 아이템입니다. |"],
            ),
        ],
        time_scope="historical",
    ),
    # dnf_monthly_item
    case(
        "dnf_monthly_item",
        "table_attribute",
        "document_sha256_797da951520c83628fb0434ff6162b7d3e96656821f51667e0c1a770586f3c81",
        "2025년 12월 스페셜 클론 레어 아바타 풀세트 상자의 상점 판매가격과 거래 타입은 뭐였어?",
        [
            requirement(
                "shop_price",
                "2025년 12월 스페셜 클론 레어 아바타 풀세트 상자",
                "shop_price",
                "currency",
                [{"amount": 40000000, "unit": "골드"}],
                ["# [12월 이달의 아이템] : [12월]스페셜 클론 레어 아바타 풀세트 상자\n[TABLE]\n| 구분 | 이달의 아이템 |\n| 아이템명 | [12월]스페셜 클론 레어 아바타 풀세트 상자 |\n| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 교환가능 |"],
            ),
            requirement(
                "trade_type",
                "2025년 12월 스페셜 클론 레어 아바타 풀세트 상자",
                "trade_type",
                "enum",
                ["교환가능"],
                ["# [12월 이달의 아이템] : [12월]스페셜 클론 레어 아바타 풀세트 상자\n[TABLE]\n| 구분 | 이달의 아이템 |\n| 아이템명 | [12월]스페셜 클론 레어 아바타 풀세트 상자 |\n| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 교환가능 |"],
            ),
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "temporal_role",
        "document_sha256_2c55b66582aafe1daabe2d338479754fff2b85fb397134606401fbd562a35a5d",
        "2025년 11월 시브의 보조장비 보주는 삭제 기한이 정해져 있었어?",
        [
            requirement(
                "has_deletion_deadline",
                "2025년 11월 시브의 보조장비 보주",
                "has_deletion_deadline",
                "boolean",
                [False],
                ["# [11월 이달의 아이템] : 시브의 보조장비 보주\n[TABLE]\n| 구분 | 이달의 아이템 |\n| 아이템명 | 시브의 보조장비 보주 |\n| 아이콘 | |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 1회 교환가능(거래 후 계정귀속) |\n| 툴팁 | 모든 속성 강화 +12 물리 크리티컬 히트 +3% 마법 크리티컬 히트 +3% 공격력 증폭 +3% 모험가 명성 +221 |\n| 삭제일자 | 무제한 |"],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "revision_selection",
        "document_sha256_8d15942b7c803029b811a23910302f2274bd00a85d68f3c8be8d1a6510122be6",
        "2026년 6월 찬란한 엠블렘 풀세트 선택상자에서는 선택한 한 종류의 엠블렘을 몇 개 받았어?",
        [
            requirement(
                "selected_emblem_quantity",
                "2026년 6월 찬란한 엠블렘 풀세트 선택상자",
                "selected_emblem_quantity",
                "number",
                [4],
                ["# [6월 이달의 아이템] : [6월]스페셜 클론 레어 아바타 풀세트 상자\n[TABLE]\n| 구분 | 이달의 아이템 |\n| 아이템명 | [6월]스페셜 클론 레어 아바타 풀세트 상자 |\n| 아이콘 | [IMAGE_ALT] 스페셜 클론 레어 아바타 풀세트 상자 |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 교환가능 |\n| 툴팁 | 사용 시 [6월]클론 레어 아바타(교환불가) 풀세트 상자와 [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자를 얻을 수 있습니다. [6월]클론 레어 아바타(교환불가) 풀세트 상자, [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자는 교환가능 아이템입니다. [6월]클론 레어 아바타(교환불가)풀세트 상자 사용 시 클론 레어 아바타(교환불가) 풀세트를 획득할 수 있습니다. [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자를 사용하여 획득한 엠블렘은 계정귀속, 합성불가 타입이며 교환불가 아바타에만 장착할 수 있습니다. 획득한 모든 아이템은 2026년 7월 9일 06시 일괄 삭제됩니다. |\n| 삭제일자 | 2026년 7월 9일 06시 일괄삭제 |\n[/TABLE]\n* 스페셜 클론 레어 아바타 풀세트 상자 구성품\n[TABLE]\n| 구분 | 스페셜 클론 레어 아바타 풀세트 상자 구성품 |\n| 아이템명 | [6월]클론 레어 아바타(교환불가) 풀세트 상자 | [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자 |\n| 아이콘 | [IMAGE_ALT] 클론 레어 아바타(교환불가) 풀세트 상자 | [IMAGE_ALT] 찬란한 엠블렘(계정귀속) 풀세트 선택상자 |\n| 거래타입 | 교환가능 | 교환가능 |\n| 툴팁 | 클론 레어 아바타(교환불가) 8부위를 받을 수 있습니다. | 찬란한 붉은빛 엠블렘 상자, 찬란한 노란빛 엠블렘 상자, 찬란한 녹색빛 엠블렘 상자, 찬란한 푸른빛 엠블렘 상자를 얻을 수 있습니다. 엠블렘 상자는 계정귀속 아이템으로 제공됩니다. 엠블렘 상자를 사용하여 획득한 엠블렘은 계정귀속, 합성불가이며 교환불가 아바타에만 장착할 수 있습니다. 획득한 엠블렘은 2026년 7월 9일 06시에 일괄 삭제됩니다. |\n| 삭제일자 | 2026년 7월 9일 06시 일괄삭제 | 2026년 7월 9일 06시 일괄삭제 |\n[/TABLE]\n- [6월]찬란한 엠블렘(계정귀속) 풀세트 선택상자에서 선택 가능한 엠블렘 목록입니다.\n- 선택한 한 종류의 엠블렘 4개를 획득할 수 있습니다."],
            )
        ],
        time_scope="historical",
    ),
    case(
        "dnf_monthly_item",
        "unsupported_or_partial",
        "document_sha256_aa29165b9617ffd053c975a270d8da5b25339a564f95cb7bf46604788b8baec8",
        "2026년 5월 고대의 바인드 큐브 8개 상자의 거래 타입과 계정당 구매 제한을 알려줘.",
        [
            requirement(
                "trade_type",
                "2026년 5월 고대의 바인드 큐브 8개 상자",
                "trade_type",
                "enum",
                ["교환가능"],
                ["# [5월 이달의 아이템] : 고대의 바인드 큐브 8개 상자\n[TABLE]\n| 구분 | 이달의 아이템 |\n| 아이템명 | 고대의 바인드 큐브 8개 상자 |\n| 아이콘 | |\n| 상점판매가격 | 4,000만 골드 |\n| 거래타입 | 교환가능 |"],
            ),
            requirement(
                "account_purchase_limit",
                "2026년 5월 고대의 바인드 큐브 8개 상자",
                "account_purchase_limit",
                "text",
                [],
                [],
                expected_status="unsupported",
            ),
        ],
        time_scope="historical",
        expected_response_mode="partial_answer",
    ),
]


def main() -> None:
    base.SPECS = SPECS
    base.AS_OF = "2026-07-28"
    base.BUILDER_VERSION = "typed-evidence-ref-untouched32-draft-builder-20260728-v2"
    base.PARENT_OVERLAP_NOTE = (
        "기존 평가에 등장한 parent가 포함될 수 있으나 질문과 claim은 새로 작성했습니다. "
        "이 세트는 parent-blind가 아닌 신규 claim/question 미실행 세트이며, "
        "사람 검수 후에만 freeze 및 최초 실행할 수 있습니다."
    )
    base.main()


if __name__ == "__main__":
    main()
