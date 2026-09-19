"""
RAGAS-style evaluation script (§13).
Runs a fixed set of handwritten Q&A pairs against the base knowledge base,
scoring faithfulness and answer relevancy. Prints a summary report.

Usage:
    python -m eval.ragas_eval

Requires the backend server to be running at http://localhost:8000.
"""

import asyncio
import json
import sys
import time
import httpx
from dataclasses import dataclass


@dataclass
class EvalCase:
    """A single evaluation case with expected answer and source."""
    question: str
    expected_answer_keywords: list[str]  # key phrases that should appear
    expected_source: str  # filename that should be cited
    category: str  # topic category for reporting


# -------------------------------------------------------------------------
# Evaluation dataset — 10 handwritten Q&A pairs (§13)
# Replace these with actual questions about YOUR base knowledge PDFs.
# -------------------------------------------------------------------------
EVAL_CASES = [
    EvalCase(
        question="What is retrieval augmented generation?",
        expected_answer_keywords=["retrieval", "generation", "knowledge"],
        expected_source="",  # fill with actual base PDF filename
        category="Core Concepts",
    ),
    EvalCase(
        question="How does vector similarity search work?",
        expected_answer_keywords=["vector", "similarity", "embedding"],
        expected_source="",
        category="Core Concepts",
    ),
    EvalCase(
        question="What are the benefits of chunking documents?",
        expected_answer_keywords=["chunk", "context", "retrieval"],
        expected_source="",
        category="Ingestion",
    ),
    EvalCase(
        question="How does BM25 differ from dense retrieval?",
        expected_answer_keywords=["BM25", "sparse", "keyword"],
        expected_source="",
        category="Retrieval",
    ),
    EvalCase(
        question="What is reranking and why is it used?",
        expected_answer_keywords=["rerank", "relevance", "quality"],
        expected_source="",
        category="Retrieval",
    ),
    EvalCase(
        question="How are citations generated and validated?",
        expected_answer_keywords=["citation", "source", "reference"],
        expected_source="",
        category="Generation",
    ),
    EvalCase(
        question="What is the purpose of conversation memory?",
        expected_answer_keywords=["memory", "conversation", "context"],
        expected_source="",
        category="Memory",
    ),
    EvalCase(
        question="How does the LLM fallback chain work?",
        expected_answer_keywords=["fallback", "provider", "retry"],
        expected_source="",
        category="LLM Routing",
    ),
    EvalCase(
        question="What is the recipe for banana bread?",
        expected_answer_keywords=[],  # should get fallback — no relevant docs
        expected_source="",
        category="Out of Scope (should fail)",
    ),
    EvalCase(
        question="What are embedding models used for in RAG systems?",
        expected_answer_keywords=["embedding", "vector", "representation"],
        expected_source="",
        category="Core Concepts",
    ),
]

FALLBACK_MESSAGE = "I don't have enough information in the provided documents to answer that."
API_BASE = "http://localhost:8000"


async def create_session(client: httpx.AsyncClient) -> str:
    """Create a new session and return session_id."""
    resp = await client.post(f"{API_BASE}/session")
    resp.raise_for_status()
    return resp.json()["session_id"]


async def ask_question(
    client: httpx.AsyncClient, session_id: str, question: str
) -> dict:
    """Ask a question and collect the full streamed response."""
    answer_text = ""
    citations = []
    provider_used = "unknown"

    async with client.stream(
        "POST",
        f"{API_BASE}/ask",
        json={"session_id": session_id, "question": question},
        timeout=60.0,
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "token":
                        answer_text += data.get("content", "")
                    elif data.get("type") == "final":
                        final = data.get("data", {})
                        answer_text = final.get("answer", answer_text)
                        citations = final.get("citations", [])
                        provider_used = final.get("provider_used", "unknown")
                except json.JSONDecodeError:
                    pass

    return {
        "answer": answer_text,
        "citations": citations,
        "provider_used": provider_used,
    }


def score_faithfulness(answer: str, citations: list[dict]) -> float:
    """
    Simple faithfulness score: proportion of answer that is backed by citations.
    1.0 = has citations, 0.0 = no citations at all.
    More sophisticated: check citation density per sentence.
    """
    if answer == FALLBACK_MESSAGE:
        return 1.0  # correctly refusing to answer is faithful

    if not citations:
        return 0.0

    # Count sentences with at least one citation marker
    import re
    sentences = [s.strip() for s in re.split(r'[.!?]', answer) if s.strip()]
    if not sentences:
        return 0.0

    cited_sentences = sum(1 for s in sentences if re.search(r'\[\d+\]', s))
    return cited_sentences / len(sentences)


def score_answer_relevancy(
    answer: str, expected_keywords: list[str], is_out_of_scope: bool
) -> float:
    """
    Simple answer relevancy: how many expected keywords appear in the answer.
    For out-of-scope questions, check that the fallback message is returned.
    """
    if is_out_of_scope:
        # Should get the fallback message, NOT a hallucinated answer
        if FALLBACK_MESSAGE in answer:
            return 1.0
        return 0.0

    if not expected_keywords:
        return 0.5  # no expectations set

    answer_lower = answer.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return found / len(expected_keywords)


async def run_evaluation():
    """Run all eval cases and print summary report."""
    print("=" * 70)
    print("RAGAS-Style Evaluation — Mini AI Knowledge Assistant")
    print("=" * 70)
    print()

    async with httpx.AsyncClient() as client:
        # Check server health
        try:
            resp = await client.get(f"{API_BASE}/health", timeout=5.0)
            health = resp.json()
            if health.get("status") != "ready":
                print(f"ERROR: Server not ready (status: {health.get('status')})")
                sys.exit(1)
        except Exception as e:
            print(f"ERROR: Cannot reach server at {API_BASE}: {e}")
            sys.exit(1)

        print(f"Server ready. Running {len(EVAL_CASES)} evaluation cases...\n")

        # Create a session
        session_id = await create_session(client)
        print(f"Session: {session_id}\n")

        results = []
        total_faithfulness = 0.0
        total_relevancy = 0.0

        for i, case in enumerate(EVAL_CASES, 1):
            print(f"[{i}/{len(EVAL_CASES)}] {case.category}: {case.question[:60]}...")

            start = time.time()
            try:
                response = await ask_question(client, session_id, case.question)
                elapsed = time.time() - start

                is_oos = "out of scope" in case.category.lower()
                faithfulness = score_faithfulness(
                    response["answer"], response["citations"]
                )
                relevancy = score_answer_relevancy(
                    response["answer"], case.expected_answer_keywords, is_oos
                )

                total_faithfulness += faithfulness
                total_relevancy += relevancy

                result = {
                    "case": i,
                    "category": case.category,
                    "question": case.question,
                    "answer_preview": response["answer"][:100] + "..."
                        if len(response["answer"]) > 100 else response["answer"],
                    "citations_count": len(response["citations"]),
                    "provider": response["provider_used"],
                    "faithfulness": faithfulness,
                    "relevancy": relevancy,
                    "elapsed_s": round(elapsed, 2),
                    "is_fallback": FALLBACK_MESSAGE in response["answer"],
                }
                results.append(result)

                status = "✓" if (faithfulness >= 0.5 or is_oos) else "✗"
                print(
                    f"  {status} Faith: {faithfulness:.2f} | "
                    f"Relev: {relevancy:.2f} | "
                    f"Citations: {len(response['citations'])} | "
                    f"Provider: {response['provider_used']} | "
                    f"{elapsed:.1f}s"
                )

            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                results.append({
                    "case": i,
                    "category": case.category,
                    "question": case.question,
                    "error": str(e),
                    "faithfulness": 0.0,
                    "relevancy": 0.0,
                })

        # Summary
        n = len(EVAL_CASES)
        avg_faith = total_faithfulness / n if n > 0 else 0
        avg_relev = total_relevancy / n if n > 0 else 0

        print()
        print("=" * 70)
        print("EVALUATION SUMMARY")
        print("=" * 70)
        print(f"Total cases:            {n}")
        print(f"Avg faithfulness:       {avg_faith:.3f}")
        print(f"Avg answer relevancy:   {avg_relev:.3f}")
        print()

        # Per-category breakdown
        categories = {}
        for r in results:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = {"faith": [], "relev": []}
            categories[cat]["faith"].append(r.get("faithfulness", 0))
            categories[cat]["relev"].append(r.get("relevancy", 0))

        print("Per-category scores:")
        for cat, scores in categories.items():
            avg_f = sum(scores["faith"]) / len(scores["faith"])
            avg_r = sum(scores["relev"]) / len(scores["relev"])
            print(f"  {cat:30s} Faith: {avg_f:.2f}  Relev: {avg_r:.2f}")

        print()
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_evaluation())

