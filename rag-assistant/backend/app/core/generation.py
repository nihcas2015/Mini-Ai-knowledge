"""
Prompt building, streaming, citation validation, and conversation memory updates.
Exact implementation per SPEC.md §6.
"""

import re
import asyncio
import logging
from typing import AsyncGenerator

from app.config import settings
from app.models.schemas import Citation, AskResponse

logger = logging.getLogger(__name__)

# System prompt establishing identity and flexible RAG behavior
SYSTEM_PROMPT = (
    "You are the Mini AI Knowledge System, an advanced intelligent assistant designed and built by Sachin.\n\n"
    "Identity Rules (STRICT):\n"
    "- If asked who you are, what you are, or who created/built you, ALWAYS state that you are the 'Mini AI Knowledge System built by Sachin'.\n"
    "- NEVER mention, acknowledge, or cite any underlying AI models or companies (do NOT mention OpenAI, GPT, Google, Gemini, Meta, LLaMA, Anthropic, Groq, etc.). You are solely the Mini AI Knowledge System built by Sachin.\n\n"
    "Answering Guidelines:\n"
    "1. When numbered context passages ([1], [2], etc.) are provided below: Ground your primary answer in that context and cite every claim using [1], [2], etc. In addition to the grounded facts, provide helpful explanations, code snippets, or background so the answer is thorough, clear, and easy to understand rather than cold or rigid.\n"
    "2. When no context passages match (e.g. greetings, general questions, broad topics): Answer politely, thoroughly, and intelligently from your broad knowledge, and gently mention that the user can also upload PDFs to explore specific documents."
)

FALLBACK_MESSAGE = "I don't have enough information in the provided documents to answer that."
UNAVAILABLE_MESSAGE = "The assistant is temporarily unavailable. Please try again in a moment."


def build_context_block(chunks: list[dict]) -> str:
    """
    Build the numbered context block for the LLM prompt (§6 step 1).
    Format: [n] (source: filename, page X, base/user knowledge)\n<parent_text>
    """
    if not chunks:
        return ""

    parts = []
    for i, chunk in enumerate(chunks, 1):
        filename = chunk.get("filename", "unknown")
        page = chunk.get("page_number", "?")
        source_type = chunk.get("source_type", "base")
        source_label = "base knowledge" if source_type == "base" else "user upload"
        parent_text = chunk.get("parent_text", chunk.get("child_text", ""))

        parts.append(
            f"[{i}] (source: {filename}, page {page}, {source_label})\n{parent_text}"
        )

    return "\n\n".join(parts)


def build_user_message(
    question: str,
    context_block: str,
    running_summary: str = "",
    last_turn: tuple[str, str] | None = None,
    recent_turns: list[tuple[str, str]] | None = None,
) -> str:
    """Build the full user message for the LLM (§6 step 3)."""
    msg_parts = []

    if running_summary:
        msg_parts.append(f"Previous conversation summary:\n{running_summary}")

    if recent_turns and len(recent_turns) > 0:
        history_lines = ["Recent conversation:"]
        for q, a in recent_turns:
            history_lines.append(f"Q: {q}\nA: {a}")
        msg_parts.append("\n".join(history_lines))
    elif last_turn:
        msg_parts.append(
            f"Last exchange:\nQ: {last_turn[0]}\nA: {last_turn[1]}"
        )

    msg_parts.append(f"Context:\n{context_block}")
    msg_parts.append(f"Question: {question}")

    return "\n\n".join(msg_parts)


def parse_citations(answer_text: str, chunks: list[dict]) -> list[Citation]:
    """
    Parse bracket citations [n] from the LLM answer and map to chunk metadata (§6 step 6).
    Drops hallucinated citations (references to indices not in the provided context).
    Deduplicates by marker number.
    """
    citations = []
    seen_markers = set()

    for match in re.finditer(r"\[(\d+)\]", answer_text):
        marker = int(match.group(1))

        # Skip duplicates
        if marker in seen_markers:
            continue

        # Skip hallucinated references (out of range)
        if marker < 1 or marker > len(chunks):
            logger.warning(
                f"Dropping hallucinated citation [{marker}] — only {len(chunks)} chunks provided"
            )
            continue

        seen_markers.add(marker)
        chunk = chunks[marker - 1]

        citations.append(
            Citation(
                marker=marker,
                filename=chunk.get("filename", "unknown"),
                page_number=chunk.get("page_number", 0),
                source_type=chunk.get("source_type", "base"),
                snippet=chunk.get("parent_text", chunk.get("child_text", "")),
            )
        )

    return citations


async def condense_question(
    question: str,
    running_summary: str,
    last_turn: tuple[str, str],
    llm_router,
) -> str:
    """
    Condense a follow-up question into a standalone question using the LLM (§5 step 1).
    Only called when conversation history exists.
    """
    system = (
        "Rewrite the user's latest question as a fully standalone question, "
        "using the conversation summary and last exchange for context. "
        "Output ONLY the rewritten question, nothing else."
    )
    user_msg = (
        f"Conversation summary: {running_summary}\n\n"
        f"Last question: {last_turn[0]}\n"
        f"Last answer: {last_turn[1]}\n\n"
        f"New question: {question}\n\n"
        f"Standalone question:"
    )

    try:
        result = await llm_router.generate(
            system_prompt=system, user_message=user_msg, stream=False
        )
        condensed = str(result).strip()
        return condensed if condensed else question
    except Exception as e:
        logger.warning(f"Question condensation failed, using original: {e}")
        return question


async def update_running_summary(
    current_summary: str,
    question: str,
    answer: str,
    llm_router,
) -> str:
    """
    Fold the latest Q&A turn into the running conversation summary (§6 step 8).
    Capped at ~200 tokens.
    """
    system = (
        "You summarize conversations. Combine the existing summary with the new "
        "Q&A turn into a single concise summary. Keep it under 200 tokens. "
        "Output ONLY the updated summary."
    )
    user_msg = (
        f"Current summary: {current_summary or '(none yet)'}\n\n"
        f"New question: {question}\n"
        f"New answer: {answer}\n\n"
        f"Updated summary:"
    )

    try:
        result = await llm_router.generate(
            system_prompt=system, user_message=user_msg, stream=False
        )
        return str(result).strip()
    except Exception as e:
        logger.warning(f"Summary update failed: {e}")
        return current_summary
