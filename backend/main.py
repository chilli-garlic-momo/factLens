import json
import os
import re
from typing import List, Dict, Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----- FastAPI app -----

app = FastAPI(title="FactLens Demo Backend (No External LLM)")

# Allow requests from the extension / browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # OK for demo; tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Load KG -----

KG_PATH = os.path.join(os.path.dirname(__file__), "kg.json")
with open(KG_PATH, "r", encoding="utf-8") as f:
    KG = json.load(f)

ENTITIES = KG["entities"]
SOURCES = {s["id"]: s for s in KG["sources"]}
FACTS = KG["facts"]
ENTITIES_BY_ID = {e["id"]: e for e in ENTITIES}


# ----- Pydantic models -----

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


# ----- Helpers: entity detection + KG search -----

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


# ----- "Fake agent" logic tailored to your 3 demo claims -----

def extract_claims(text: str) -> List[str]:
    """
    For this demo, treat the entire post text as ONE claim.
    Your Reddit posts should contain the claim sentence clearly.
    """
    t = text.strip()
    return [t] if t else []


def assess_claim_rule_based(claim: str, kg_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Simple rule-based 'agent' that uses KG facts to decide verdicts
    for 3 patterns:
      - C1: Amber warning issued
      - C2: Metro runs on normal schedule, no shutdown
      - C3: Rumour that all metro is cancelled and NWB said metro won't run
    """

    lower = claim.lower()

    def has_fact(fid: str) -> bool:
        return any(e["fact_id"] == fid for e in kg_evidence)

    # Convenience booleans
    has_amber = has_fact("fact_nwb_amber_lakeside_2023_03_21")
    has_metro_normal = has_fact("fact_lmr_operational_2023_03_21")
    has_nwb_role = has_fact("fact_nwb_no_transport_decisions")

    # --- Claim 1: Amber warning for Lakeside City ---
    if (
        "northwind weather bureau" in lower
        and "amber rain warning" in lower
        and "lakeside city" in lower
    ):
        if has_amber:
            return {
                "verdict": "True",
                "confidence": 0.95,
                "citations": ["fact_nwb_amber_lakeside_2023_03_21"],
                "reasoning": (
                    "The knowledge graph contains a fact stating that Northwind Weather Bureau issued an amber "
                    "rain warning for Lakeside City on 21 March 2023. This directly supports the claim."
                )
            }
        else:
            return {
                "verdict": "Unverifiable",
                "confidence": 0.4,
                "citations": [],
                "reasoning": "No matching weather warning fact was found in the knowledge graph."
            }

    # --- Claim 2: Metro runs on normal weekday schedule; no full shutdown ---
    if (
        "lakeside metro rail" in lower
        and "normal weekday schedule" in lower
        and ("no full network shutdown" in lower or "no full shutdown" in lower)
    ):
        if has_metro_normal:
            return {
                "verdict": "True",
                "confidence": 0.95,
                "citations": ["fact_lmr_operational_2023_03_21"],
                "reasoning": (
                    "The knowledge graph contains a fact from Lakeside Metro Rail stating that all lines will "
                    "operate on a normal weekday schedule on 21 March 2023 and that no full network shutdown "
                    "is planned. This matches the claim."
                )
            }
        else:
            return {
                "verdict": "Unverifiable",
                "confidence": 0.4,
                "citations": [],
                "reasoning": "No matching service-status fact for Lakeside Metro Rail was found in the knowledge graph."
            }

    # --- Claim 3: Rumour of total cancellation & NWB supposedly saying metro won't run ---
    if (
        "all lakeside metro rail services" in lower and
        ("cancelled" in lower or "canceled" in lower)
    ) or ("metro will not run" in lower):
        if has_amber and has_metro_normal and has_nwb_role:
            return {
                "verdict": "Partly True",
                "confidence": 0.9,
                "citations": [
                    "fact_nwb_amber_lakeside_2023_03_21",
                    "fact_lmr_operational_2023_03_21",
                    "fact_nwb_no_transport_decisions"
                ],
                "reasoning": (
                    "The knowledge graph confirms that an amber rain warning is in effect for Lakeside City on "
                    "21 March 2023. However, Lakeside Metro Rail has announced that all lines will operate on a "
                    "normal weekday schedule and that no full network shutdown is planned. In addition, the "
                    "Northwind Weather Bureau states that it does not announce closures of metro or other public "
                    "transport. Therefore the part of the claim about the weather warning is true, but the parts "
                    "about all metro services being cancelled and NWB saying the metro will not run are not "
                    "supported and are contradicted by the available evidence."
                )
            }
        else:
            return {
                "verdict": "Unverifiable",
                "confidence": 0.4,
                "citations": [],
                "reasoning": (
                    "The claim alleges complete cancellation of metro services and that the weather bureau said the "
                    "metro will not run, but the knowledge graph does not contain enough conflicting or supporting "
                    "evidence to decide this claim."
                )
            }

    # --- Default fallback for any other text ---
    return {
        "verdict": "Unverifiable",
        "confidence": 0.5,
        "citations": [],
        "reasoning": "The claim does not match any known patterns in this demo knowledge graph."
    }


# ----- /verify endpoint -----

@app.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest):
    # 1) Extract claims (single-claim stub)
    claims = extract_claims(req.text)
    if not claims:
        return VerifyResponse(
            claim="",
            verdict="Unverifiable",
            confidence=0.5,
            citations=[],
            reasoning="No verifiable factual claim found in the text."
        )

    claim = claims[0]

    # 2) Extract entities from the claim
    entity_ids = extract_entities(claim)

    # 3) Search KG for evidence
    kg_evidence = search_kg(claim, entity_ids=entity_ids, top_k=5)

    # 4) Rule-based assessment using only KG evidence
    assessment = assess_claim_rule_based(claim, kg_evidence)

    # 5) Build response with citations
    citations: List[Citation] = []
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