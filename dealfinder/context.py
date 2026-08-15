"""Context engineering — treat the context window as RAM, not storage.

Everything the agent reasons over — system prompt, tool schemas, retrieved deals,
and the running conversation — competes for one finite token budget. Retrieval
(Parts 5/13/14) decides *what is relevant*; context engineering decides *what
actually goes in the window, in what order, and what to evict* when it fills.

Three levers, all grounded in the real DealFinder context:

- **Budgeting** — count tokens and pack only what fits. Retrieve wide (k=20), then
  drop the tail so the retrieved block fits its slice of the window.
- **Ordering** — models attend best to the START and END of the context ("lost in
  the middle"), so place the strongest picks at the extremes, not buried.
- **Compaction** — a multi-turn deal chat grows without bound; summarize old turns
  into a compact state line and keep only the most recent turns verbatim.

Token counts use the same bge-small tokenizer the course already caches, so they
are real and reproducible offline. In production you would count with the
*generator's* tokenizer (e.g. tiktoken for GPT); the budgeting logic is identical.
"""
from __future__ import annotations

import glob
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache

from tokenizers import Tokenizer

from . import rag


def _tokenizer_roots() -> list[str]:
    """Cache roots a bge-small embed step may have written the tokenizer to.

    Different backends cache it in different places: sentence-transformers uses
    the HF hub cache (BAAI/bge-small-en-v1.5); fastembed — what embed.py actually
    uses — caches the ONNX repo (qdrant/bge-small-en-v1.5-onnx-q) under its own
    cache dir (FASTEMBED_CACHE_PATH, else <tmp>/fastembed_cache). Search all so
    token counts work regardless of which backend warmed the model."""
    return [
        os.path.expanduser("~/.cache/huggingface/hub"),
        os.environ.get("FASTEMBED_CACHE_PATH", ""),
        os.path.join(tempfile.gettempdir(), "fastembed_cache"),
        os.path.expanduser("~/.cache/fastembed"),
    ]


def _find_tokenizer_path(roots: list[str] | None = None) -> str:
    """Locate a cached bge-small ``tokenizer.json`` across known cache roots."""
    for root in roots if roots is not None else _tokenizer_roots():
        if not root:
            continue
        hits = [
            h for h in glob.glob(os.path.join(root, "**", "tokenizer.json"), recursive=True)
            if "bge-small" in h.lower()
        ]
        if hits:
            return sorted(hits)[0]
    raise FileNotFoundError("bge-small tokenizer not cached — run any embed step first")


@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    """The cached bge-small WordPiece tokenizer (offline, no download)."""
    return Tokenizer.from_file(_find_tokenizer_path())


def count_tokens(text: str) -> int:
    """Real token count for ``text`` (bge WordPiece). Reproducible and offline."""
    return len(_tokenizer().encode(text).ids)


@dataclass
class Packed:
    """The result of packing retrieved deals into a token budget."""

    included: list[rag.RetrievedItem]
    dropped: list[rag.RetrievedItem]
    tokens: int
    budget: int


def pack_deals(items: list[rag.RetrievedItem], budget_tokens: int) -> Packed:
    """Greedily include retrieved deal lines (as ``rag.build_context`` formats them)
    in rank order until the token budget is exhausted; drop the rest.

    This is the "context as RAM" move: you retrieved 20 candidates, but only a
    handful fit alongside the system prompt and tool schemas, so you keep the
    best-ranked ones and evict the tail.
    """
    included: list[rag.RetrievedItem] = []
    dropped: list[rag.RetrievedItem] = []
    used = 0
    for it in items:
        line = rag.build_context([it])  # one numbered line, exactly as the LLM sees it
        cost = count_tokens(line)
        if used + cost <= budget_tokens:
            included.append(it)
            used += cost
        else:
            dropped.append(it)
    return Packed(included=included, dropped=dropped, tokens=used, budget=budget_tokens)


def lost_in_the_middle(items: list[rag.RetrievedItem]) -> list[rag.RetrievedItem]:
    """Reorder a rank-sorted list so the strongest picks sit at the START and END.

    Transformers recover information at the edges of a long context far better than
    in the middle. Given items ranked best→worst, interleave them to the two ends:
    the top pick leads, the 2nd sits last, the 3rd is second, and so on — burying
    only the weakest in the middle.
    """
    head: list[rag.RetrievedItem] = []
    tail: list[rag.RetrievedItem] = []
    for i, it in enumerate(items):
        (head if i % 2 == 0 else tail).append(it)
    return head + tail[::-1]


@dataclass
class Compacted:
    """A compacted conversation: a summary line plus recent verbatim turns."""

    text: str
    turns_before: int
    turns_kept: int
    tokens_before: int
    tokens_after: int


def compact_history(turns: list[str], keep_recent: int = 2) -> Compacted:
    """Compact a multi-turn deal chat: summarize old turns into one state line,
    keep the most recent ``keep_recent`` verbatim.

    Old turns are lossily folded into a compact "so far" line (the queries seen);
    recent turns stay verbatim because that is where the live intent lives. Returns
    the compacted text and the before/after token counts so the saving is visible.
    """
    before = "\n".join(turns)
    if len(turns) <= keep_recent:
        n = count_tokens(before)
        return Compacted(text=before, turns_before=len(turns), turns_kept=len(turns),
                         tokens_before=n, tokens_after=n)

    old, recent = turns[:-keep_recent], turns[-keep_recent:]
    # Compaction preserves the *evolving intent* — the trail of user queries — and
    # drops verbose assistant prose, which is the bulk of the tokens and the least
    # useful to carry forward.
    intents = [_user_intent(t) for t in old if _user_intent(t)]
    summary = "[earlier queries: " + " → ".join(intents) + "]"
    after_text = "\n".join([summary, *recent])
    return Compacted(
        text=after_text,
        turns_before=len(turns),
        turns_kept=keep_recent,
        tokens_before=count_tokens(before),
        tokens_after=count_tokens(after_text),
    )


def _user_intent(turn: str) -> str:
    """The user's ask from a turn, or '' for assistant turns."""
    line = turn.strip().split("\n", 1)[0]
    lower = line.lower()
    if not (lower.startswith("user:") or lower.startswith("user ")):
        return ""
    return line.split(":", 1)[1].strip() if ":" in line else line
