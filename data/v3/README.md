# data/v3

v3 전용 코퍼스 경로다. `raw_snapshots/`는 immutable, `normalized/`는 revision-aware 문서, `chunks/`는 인용 가능한 청크, `structured/`는 문서에서 추출한 구조화 fact를 저장한다.

기존 `data/raw/`, `data/processed/`, `data/eval/` artifact를 이 경로 생성 과정에서 수정하지 않는다.

`raw_snapshots/`의 snapshot과 manifest, `normalized/`의 문서는 content-addressed 이름을 사용한다. 같은 이름의 artifact가 이미 있으면 byte equality를 확인해 재사용하고, 내용이 다르면 덮어쓰지 않고 실패한다. `latest` 별칭은 만들지 않는다.

현재 snapshot·manifest·revision 규칙은 `docs/v3/raw_snapshot_and_revision_contract.md`에 기록한다.
