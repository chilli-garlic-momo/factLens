import json
import os
import re
from typing import List, Dict, Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

# Load env vars
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="FactLens Demo Backend")

# CORS for local extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for demo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Load KG -----

with open("kg.json", "r", encoding="utf-8") as f:
    KG = json.load(f)

ENTITIES = KG["entities"]
SOURCES = {s["id"]: s for s in KG["sources"]}
FACTS = KG["facts"]
ENTITIES_BY_ID = {e["id"]: e for e in ENTITIES}


# ----- Models -----

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


# ----- Simple entity extraction -----

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


# ----- KG search -----

def tokenize(s: str) -> List[str]:
    return re.findall(r"\w+", s.lower())


def search_kg(query: str, entity_ids: Optional[List[str]] = None, top_k: int = 5) -> List[Dict[str, Any]]:
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
            if subject_id not in entity_ids and not any(eid in entity_ids for eid in loc_ids):
                continue

        text_fields = [
            fact.get("object_label", ""),
            fact.get("evidence_snippet", "")
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
    results = []
    for score, fact in scored_facts[:top_k]:
        subj = ENTITIES_BY_ID.get(fact["subject_entity_id"])
        src = SOURCES.get(fact["source_id"])
        result = {
            "fact_id": fact["id"],
            "score": float(score),
            "subject": {
                "id": subj["id"],
                "name": subj["name"],
                "type": subj["type"]
            } if subj else None,
            "predicate": fact.get("predicate"),
            "object_label": fact.get("object_label"),
            "object_type": fact.get("object_type"),
            "date": fact.get("date"),
            "severity": fact.get("severity"),
            "location_entities": [
                ENTITIES_BY_ID[lid] for lid in fact.get("location_entity_ids", []) if lid in ENTITIES_BY_ID
            ],
            "source": {
                "id": src["id"],
                "title": src["title"],
                "publisher": src["publisher"],
                "published_at": src["published_at"],
                "url": src["url"]
            } if src else None,
            "evidence_snippet": fact.get("evidence_snippet")
        }
        results.append(result)

    return results


# ----- LLM helpers -----

def extract_claims_via_llm(text: str) -> List[str]:
    """
    Ask the model to extract verifiable factual claims from a post.
    Returns a list of claim strings.
    """
    prompt = (
        "You are a claim extraction assistant.\n"
        "Given a social media post, extract verifiable factual claims.\n"
        "Return a JSON array of strings. If there are no claims, return []."
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ],
        temperature=0
    )
    content = response.choices[0].message.content
    # Be robust: try to find JSON array in content
    try:
        claims = json.loads(content)
        if isinstance(claims, list):
            return [c for c in claims if isinstance(c, str)]
    except Exception:
        # Fallback: treat whole content as one claim
        return [content.strip()]
    return []


def assess_claim_via_llm(claim: str, kg_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Give the model the claim + KG evidence and ask it to return:
    { verdict, confidence, citations, reasoning } as JSON.
    Citations must be fact_ids from the evidence list.
    """
    system_prompt = (
        "You are FactLens, a cautious fact-checking agent.\n"
        "You are given ONE claim and a list of evidence items from a knowledge graph.\n"
        "You MUST base your judgment ONLY on these evidence items.\n"
        "If evidence clearly supports the claim, verdict = 'True'.\n"
        "If evidence clearly contradicts the claim, verdict = 'False'.\n"
        "If parts are supported and parts are contradicted, verdict = 'Partly True'.\n"
        "If there is not enough relevant evidence either way, verdict = 'Unverifiable'.\n"
        "Return ONLY a JSON object with fields:\n"
        "  verdict: one of ['True','False','Partly True','Unverifiable']\n"
        "  confidence: float between 0 and 1\n"
        "  citations: array of fact_id strings, each must be from the provided evidence\n"
        "  reasoning: short explanation (2-5 sentences)\n"
        "Do NOT use any outside knowledge. Ignore any real-world facts not in the evidence."
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
            "evidence_snippet": e.get("evidence_snippet")
        }
        for e in kg_evidence
    ]

    user_content = (
        "Claim:\n"
        f"{claim}\n\n"
        "Evidence items (JSON array):\n"
        f"{json.dumps(evidence_for_model, ensure_ascii=False, indent=2)}"
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0
    )
    content = response.choices[0].message.content
    try:
        result = json.loads(content)
        # Basic validation
        if "verdict" in result and "confidence" in result and "citations" in result and "reasoning" in result:
            # ensure citations are subset of fact_ids
            valid_fact_ids = {e["fact_id"] for e in kg_evidence}
            result["citations"] = [c for c in result["citations"] if c in valid_fact_ids]
            return result
    except Exception:
        # Fallback if parsing fails
        return {
            "verdict": "Unverifiable",
            "confidence": 0.5,
            "citations": [],
            "reasoning": "Could not parse model output. Treating as unverifiable."
        }


# ----- /verify endpoint -----

@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest):
    # 1) Extract claims
    claims = extract_claims_via_llm(req.text)
    if not claims:
        return VerifyResponse(
            claim="",
            verdict="Unverifiable",
            confidence=0.5,
            citations=[],
            reasoning="No verifiable factual claim found in the text."
        )

    # For demo: take the first claim
    claim = claims[0]

    # 2) Extract entities from the claim
    entity_ids = extract_entities(claim)

    # 3) Search KG for evidence
    kg_evidence = search_kg(claim, entity_ids=entity_ids, top_k=5)

    # 4) Ask LLM to assess based on evidence
    assessment = assess_claim_via_llm(claim, kg_evidence)

    # 5) Build response
    citations = []
    for fact_id in assessment.get("citations", []):
        fact = next((f for f in FACTS if f["id"] == fact_id), None)
        if not fact:
            continue
        citations.append(
            Citation(
                fact_id=fact_id,
                source_id=fact["source_id"]
            )
        )

    return VerifyResponse(
        claim=claim,
        verdict=assessment.get("verdict", "Unverifiable"),
        confidence=float(assessment.get("confidence", 0.5)),
        citations=citations,
        reasoning=assessment.get("reasoning", "")
    )