import json

from meta_dashboard_pipeline import connect_db, init_db, reindex_ads


def main() -> None:
    init_db()
    with connect_db() as conn:
        summary = reindex_ads(conn, delete_unclassified=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
