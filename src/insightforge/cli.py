import argparse
import uuid
from pathlib import Path

import uvicorn

from insightforge.agents.graph import graph
from insightforge.config import get_settings
from insightforge.services.retriever import KnowledgeBase
from insightforge.support.graph import support_graph
from insightforge.support.store import CommerceStore


def main() -> None:
    parser = argparse.ArgumentParser(description="ServicePilot e-commerce after-sales agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Start the API and Web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    ask = subparsers.add_parser("ask", help="Run one research task")
    ask.add_argument("query")

    chat = subparsers.add_parser("chat", help="Handle one after-sales request")
    chat.add_argument("message")

    ingest = subparsers.add_parser("ingest", help="Index a UTF-8 text/Markdown file")
    ingest.add_argument("file", type=Path)

    subparsers.add_parser("reset-demo", help="Reset bundled fictional orders and actions")

    args = parser.parse_args()
    settings = get_settings()
    if args.command == "serve":
        uvicorn.run("insightforge.api:app", host=args.host, port=args.port, reload=False)
    elif args.command == "ask":
        result = graph.invoke(
            {
                "query": args.query,
                "max_iterations": settings.max_reflection_loops,
                "quality_threshold": settings.quality_threshold,
                "require_approval": False,
            },
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
        print(result.get("final_report", "No report generated"))
    elif args.command == "chat":
        thread_id = str(uuid.uuid4())
        result = support_graph.invoke(
            {"thread_id": thread_id, "message": args.message},
            config={"configurable": {"thread_id": thread_id}},
        )
        if result.get("__interrupt__"):
            print("This action requires approval. Use the API or Web UI to resume it.")
        else:
            print(result.get("final_reply", "No reply generated"))
    elif args.command == "ingest":
        if args.file.suffix.lower() not in {".txt", ".md", ".markdown"}:
            parser.error("Only UTF-8 .txt/.md files are supported")
        kb = KnowledgeBase(settings.database_path)
        chunks = kb.ingest_text(
            args.file.read_text(encoding="utf-8"), str(args.file), args.file.name
        )
        print(f"Indexed {chunks} chunks from {args.file}")
    elif args.command == "reset-demo":
        CommerceStore(settings.database_path).reset_demo()
        print("Demo orders and action records have been reset")
