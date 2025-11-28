function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

async function loadAnalysis() {
  const loadingEl = document.getElementById("loading");
  const contentEl = document.getElementById("content");
  const claimEl = document.getElementById("claim");
  const verdictBadgeEl = document.getElementById("verdictBadge");
  const confidenceEl = document.getElementById("confidence");
  const reasoningEl = document.getElementById("reasoning");
  const citationsEl = document.getElementById("citations");

  const text = getQueryParam("text");
  if (!text) {
    loadingEl.textContent = "No claim text provided.";
    return;
  }

  try {
    const res = await fetch("http://localhost:8000/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });

    if (!res.ok) {
      loadingEl.textContent = "Backend error: " + res.status;
      return;
    }

    const data = await res.json();
    console.log("FactLens dashboard: received", data);

    loadingEl.style.display = "none";
    contentEl.style.display = "block";

    // Claim
    claimEl.textContent = data.claim || text;

    // Verdict badge
    verdictBadgeEl.textContent = data.verdict || "Unverifiable";
    verdictBadgeEl.style.backgroundColor = "#e5e7eb";
    verdictBadgeEl.style.color = "#374151";

    if (data.verdict === "True") {
      verdictBadgeEl.style.backgroundColor = "#dcfce7";
      verdictBadgeEl.style.color = "#166534";
    } else if (data.verdict === "False") {
      verdictBadgeEl.style.backgroundColor = "#fee2e2";
      verdictBadgeEl.style.color = "#b91c1c";
    } else if (data.verdict === "Partly True") {
      verdictBadgeEl.style.backgroundColor = "#fef3c7";
      verdictBadgeEl.style.color = "#92400e";
    }

    const conf = data.confidence || 0;
    confidenceEl.textContent = `Confidence: ${(conf * 100).toFixed(1)}%`;

    reasoningEl.textContent = data.reasoning || "No reasoning available.";

    // Citations
    citationsEl.innerHTML = "";
    if (!data.citations || data.citations.length === 0) {
      const noCit = document.createElement("div");
      noCit.textContent = "No citations available for this claim.";
      noCit.className = "citation";
      citationsEl.appendChild(noCit);
    } else {
      for (const cit of data.citations) {
        const citDiv = document.createElement("div");
        citDiv.className = "citation";

        const titleSpan = document.createElement("span");
        titleSpan.className = "citation-title";
        titleSpan.textContent = `Fact: ${cit.fact_id}`;

        const metaSpan = document.createElement("span");
        metaSpan.className = "citation-meta";
        metaSpan.textContent = ` – Source: ${cit.source_id}`;

        citDiv.appendChild(titleSpan);
        citDiv.appendChild(metaSpan);
        citationsEl.appendChild(citDiv);
      }
    }
  } catch (err) {
    console.error("FactLens dashboard: error", err);
    loadingEl.textContent = "Error loading analysis.";
  }
}

document.addEventListener("DOMContentLoaded", loadAnalysis);