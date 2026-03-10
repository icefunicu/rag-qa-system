from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
KB_SRC = REPO_ROOT / "apps" / "services" / "knowledge-base" / "src"


def _prioritize_sys_path(path: Path) -> None:
    target = str(path)
    try:
        sys.path.remove(target)
    except ValueError:
        pass
    sys.path.insert(0, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Qdrant vectors for existing KB documents.")
    parser.add_argument("--document-id", default="", help="Only rebuild a single document ID.")
    parser.add_argument("--base-id", default="", help="Only rebuild documents for one knowledge base.")
    args = parser.parse_args()

    _prioritize_sys_path(KB_SRC)
    vector_store = importlib.import_module("app.vector_store")
    runtime = importlib.import_module("app.runtime")

    summary = {
        "status": "ok",
        "scope": {"document_id": args.document_id.strip(), "base_id": args.base_id.strip()},
        "vector_store": vector_store.ensure_vector_store(),
        "documents": [],
    }

    with runtime.db.connect() as conn:
        with conn.cursor() as cur:
            clauses = ["TRUE"]
            params: list[str] = []
            if args.document_id.strip():
                clauses.append("id = %s::uuid")
                params.append(args.document_id.strip())
            if args.base_id.strip():
                clauses.append("base_id = %s::uuid")
                params.append(args.base_id.strip())
            cur.execute(
                f"""
                SELECT id::text AS document_id
                FROM kb_documents
                WHERE {" AND ".join(clauses)}
                ORDER BY created_at ASC
                """,
                tuple(params),
            )
            rows = cur.fetchall()

    for row in rows:
        document_id = str(row["document_id"])
        vector_store.delete_document_vectors(document_id)
        section_stats = vector_store.index_document_sections(document_id)
        chunk_stats = vector_store.index_document_chunks(document_id)
        summary["documents"].append(
            {
                "document_id": document_id,
                "sections": section_stats,
                "chunks": chunk_stats,
            }
        )

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
