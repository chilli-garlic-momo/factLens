import json
import os
import re
from typing import List, Dict, Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from groq import Groq

# =========================
# Groq config
# =========================

load_dotenv()  # loads .env from this folder if present

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set. Set it in .env or hardcode it in main.py.")

client = Groq(api_key=GROQ_API_KEY)

# =========================
# FastAPI app
# =========================

app = FastAPI(title="FactLens Demo Backend (Groq LLM + KG)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # OK for demo; tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Load KG
# =========================

KG_PATH = os.path.join(os.path.dirname(__file__), "kg.json")
with open(KG_PATH, "r", encoding="utf-8") as f:
    KG = json.load(f)

ENTITIES = KG["entities"]
SOURCES = {s["id"]: s for s in KG["sources"]}
FACTS = KG["facts"]
ENTITIES_BY_ID = {e["id"]: e for e in ENTITIES}


# =========================
# Pydantic models
# =========================

class VerifyRequest(BaseModel):
    text: str


class Citation(BaseModel):
    fact_id: str
    source_id: str


class VerifyResponse(BaseModel):
    claim: str
    verdict: str
    confidence: float
    citations: List[Citation]
    reasoning: str


# =========================
# Helpers: entity detection + KG search
# =========================

def tokenize(s: str) -> List[str]:
    return re.findall(r"\w+", s.lower())


def extract_entities(text: str) -> List[str]:
    """
    Very simple entity linker:
    - if any entity name or alias appears as a substring (case-insensitive),
      we consider that entity present.
    """
    entity_ids = set()
    lower = text.lower()
    for ent in ENTITIES:
        names = [ent["name"]] + ent.get("aliases", [])
        for name in names:
            if name.lower() in lower:
                entity_ids.add(ent["id"])
                break
    return list(entity_ids)


def search_kg(
    query: str, entity_ids: Optional[List[str]] = None, top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Naive lexical search over KG facts.
    Scores based on token overlap; optionally filters by entities.
    """
    q_tokens = set(tokenize(query))
    scored_facts = []

    for fact in FACTS:
        # Entity filter
        if entity_ids:
            subject_id = fact.get("subject_entity_id")
            loc_ids = fact.get("location_entity_ids", [])
            if subject_id not in entity_ids and not any(
                eid in entity_ids for eid in loc_ids
            ):
                continue

        text_fields = [
            fact.get("object_label", ""),
            fact.get("evidence_snippet", ""),
        ]
        tokens = set()
        for field in text_fields:
            tokens.update(tokenize(field))

        overlap = q_tokens.intersection(tokens)
        if not overlap:
            continue

        score = len(overlap)
        scored_facts.append((score, fact))

    # Sort by score descending
    scored_facts.sort(key=lambda x: x[0], reverse=True)
    results: List[Dict[str, Any]] = []
    for score, fact in scored_facts[:top_k]:
        subj = ENTITIES_BY_ID.get(fact["subject_entity_id"])
        src = SOURCES.get(fact["source_id"])
        results.append(
            {
                "fact_id": fact["id"],
                "score": float(score),
                "subject": {
                    "id": subj["id"],
                    "name": subj["name"],
                    "type": subj["type"],
                }
                if subj
                else None,
                "predicate": fact.get("predicate"),
                "object_label": fact.get("object_label"),
                "object_type": fact.get("object_type"),
                "date": fact.get("date"),
                "severity": fact.get("severity"),
                "location_entities": [
                    ENTITIES_BY_ID[lid]
                    for lid in fact.get("location_entity_ids", [])
                    if lid in ENTITIES_BY_ID
                ],
                "source": {
                    "id": src["id"],
                    "title": src["title"],
                    "publisher": src["publisher"],
                    "published_at": src["published_at"],
                    "url": src["url"],
                }
                if src
                else None,
                "evidence_snippet": fact.get("evidence_snippet"),
            }
        )

    return results


# =========================
# Fallback heuristic for claims
# =========================

def _heuristic_claim_from_text(text: str) -> Optional[str]:
    """
    Simple fallback when the LLM claim extractor returns nothing or fails:
    - Split by sentence boundaries and newlines.
    - Pick the first non-trivial sentence (>= 4 tokens).
    - If none, return the whole text or None.
    This is deliberately not strict, so even short or Hinglish posts
    like 'Amber warning = Lakeside Metro cancel ho jayega?' become claims.
    """
    stripped = text.strip()
    if not stripped:
        return None

    # Split on ., ?, !, or newline
    parts = re.split(r"[.\n!?]+", stripped)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(tokenize(p)) >= 4:
            return p

    return stripped


# =========================
# LLM helpers (Groq)
# =========================

def extract_claims_via_llm(text: str) -> List[str]:
    """
    Use LLM to extract verifiable factual claims.
    We are deliberately NOT super-strict:
    - If there's any factual-looking sentence, we want at least one claim.
    - If the model is unsure, it's told to include the main sentence.
    - If parsing fails, we fall back to a heuristic.
    """
    system_prompt = (
        "You are a claim extraction assistant.\n"
        "Given a social media post, extract explicit, verifiable factual claims.\n"
        "- A factual claim is any sentence that asserts something that could be true or false.\n"
        "- If there is at least one such sentence, you MUST include at least one item.\n"
        "- If you are unsure, include the entire post text as a single claim.\n"
        "- VERY IMPORTANT: Whenever possible, copy the claim sentence VERBATIM from the post instead of paraphrasing or rewriting it.\n"
        "Return ONLY a JSON array of strings. If there are truly no factual statements, return []."
    )

    print("  [LLM] extract_claims_via_llm input text:", repr(text[:400]))

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content
        print("  [LLM] raw claim extraction output:", repr(raw[:400]))
    except Exception as e:
        print("  [LLM] ERROR in extract_claims_via_llm:", repr(e))
        hc = _heuristic_claim_from_text(text)
        return [hc] if hc else []

    # Try to parse JSON array
    try:
        claims = json.loads(raw)
        if isinstance(claims, list):
            cleaned = [c.strip() for c in claims if isinstance(c, str) and c.strip()]
            if cleaned:
                return cleaned
    except Exception as e:
        print("  [LLM] ERROR parsing claim JSON:", repr(e))

    # Fallback if model returned something but not valid JSON
    hc = _heuristic_claim_from_text(text)
    return [hc] if hc else []


def assess_claim_via_llm(
    claim: str, kg_evidence: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Use LLM to decide verdict using only KG evidence.
    We are not super-strict about exact wording; model can reason flexibly.
    """
    system_prompt = (
        "You are FactLens, a cautious fact-checking agent.\n"
        "You are given ONE claim and a list of evidence items from a knowledge graph.\n"
        "The claim may contain MULTIPLE sub-claims (e.g. about different entities or effects).\n"
        "You MUST:\n"
        "- Identify the main sub-claims in the statement.\n"
        "- Compare EACH sub-claim against the evidence items.\n"
        "- Decide an overall verdict:\n"
        "    * 'True' if all major parts are supported.\n"
        "    * 'False' if all major parts are contradicted.\n"
        "    * 'Partly True' if some major parts are supported and others contradicted.\n"
        "    * 'Unverifiable' if there is not enough relevant evidence either way.\n"
        "Return ONLY a JSON object with fields:\n"
        "  verdict: one of ['True','False','Partly True','Unverifiable']\n"
        "  confidence: float between 0 and 1\n"
        "  citations: array of fact_id strings, each must be from the provided evidence\n"
        "  reasoning: short explanation (2-5 sentences) that explicitly mentions which parts of the claim are supported or contradicted.\n"
        "You MUST base your judgment ONLY on the provided evidence items.\n"
        "Do NOT use any outside knowledge. Ignore any real-world facts not in the evidence.\n"
        "Respond with pure JSON, no markdown, no backticks."
    )

    evidence_for_model = [
        {
            "fact_id": e["fact_id"],
            "predicate": e["predicate"],
            "object_label": e["object_label"],
            "date": e.get("date"),
            "severity": e.get("severity"),
            "subject": e["subject"]["name"] if e.get("subject") else None,
            "source_title": e["source"]["title"] if e.get("source") else None,
            "source_publisher": e["source"]["publisher"] if e.get("source") else None,
            "evidence_snippet": e.get("evidence_snippet"),
        }
        for e in kg_evidence
    ]

    user_content = (
        "Claim:\n"
        f"{claim}\n\n"
        "Evidence items (JSON array):\n"
        f"{json.dumps(evidence_for_model, ensure_ascii=False, indent=2)}"
    )

    print("  [LLM] assess_claim_via_llm claim:", repr(claim))
    print(
        "  [LLM] evidence_for_model:",
        json.dumps(evidence_for_model, indent=2, ensure_ascii=False),
    )

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content
        print("  [LLM] raw assessment output:", repr(raw[:400]))
    except Exception as e:
        print("  [LLM] ERROR in assess_claim_via_llm:", repr(e))
        return {
            "verdict": "Unverifiable",
            "confidence": 0.5,
            "citations": [],
            "reasoning": "LLM call failed; treating claim as unverifiable.",
        }

    try:
        result = json.loads(raw)
        if (
            isinstance(result, dict)
            and "verdict" in result
            and "confidence" in result
            and "citations" in result
            and "reasoning" in result
        ):
            valid_fact_ids = {e["fact_id"] for e in kg_evidence}
            result["citations"] = [
                c for c in result["citations"] if c in valid_fact_ids
            ]
            try:
                conf = float(result["confidence"])
            except Exception:
                conf = 0.5
            result["confidence"] = max(0.0, min(1.0, conf))
            return result
    except Exception as e:
        print("  [LLM] ERROR parsing assessment JSON:", repr(e))

    return {
        "verdict": "Unverifiable",
        "confidence": 0.5,
        "citations": [],
        "reasoning": "Could not parse model output. Treating as unverifiable.",
    }


# =========================
# /verify endpoint
# =========================

@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest):
    print("\n====================")
    print(" /verify called")
    print(" Raw req.text:")
    print(repr(req.text))
    print("====================")

    text = (req.text or "").strip()

    if not text:
        print(" Empty text; returning Unverifiable.")
        return VerifyResponse(
            claim="",
            verdict="Unverifiable",
            confidence=0.5,
            citations=[],
            reasoning="No text provided.",
        )

    # 1) Extract claims via LLM (with fallbacks inside)
    claims = extract_claims_via_llm(text)
    print(" Extracted claims (after fallbacks):", claims)

    if not claims:
        print(" Still no claims; returning Unverifiable.")
        return VerifyResponse(
            claim="",
            verdict="Unverifiable",
            confidence=0.5,
            citations=[],
            reasoning="No verifiable factual claim found in the text.",
        )

    # For demo, use the first claim
    claim = claims[0]
    print(" Using claim:", repr(claim))

    # 2) Extract entities from the claim
    entity_ids = extract_entities(claim)
    print(" Detected entity_ids:", entity_ids)

    # 3) Search KG for evidence
    kg_evidence = search_kg(claim, entity_ids=entity_ids, top_k=5)
    print(" KG evidence fact_ids:", [e["fact_id"] for e in kg_evidence])

    if not kg_evidence:
        print(" No KG evidence; returning Unverifiable.")
        return VerifyResponse(
            claim=claim,
            verdict="Unverifiable",
            confidence=0.5,
            citations=[],
            reasoning="No relevant evidence was found in the knowledge graph.",
        )

    # 4) LLM-based assessment using only KG evidence
    assessment = assess_claim_via_llm(claim, kg_evidence)
    print(" Assessment:", assessment)

    # 5) Build response with citations
    citations: List[Citation] = []
    for fact_id in assessment.get("citations", []):
        fact = next((f for f in FACTS if f["id"] == fact_id), None)
        if not fact:
            continue
        citations.append(
            Citation(fact_id=fact_id, source_id=fact["source_id"])
        )

    resp = VerifyResponse(
        claim=claim,
        verdict=assessment.get("verdict", "Unverifiable"),
        confidence=float(assessment.get("confidence", 0.5)),
        citations=citations,
        reasoning=assessment.get("reasoning", ""),
    )

    print(" Final response:", resp.model_dump())
    print("====================\n")

    return resp