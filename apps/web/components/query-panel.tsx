"use client";

import { useState, useTransition } from "react";

import { askQuestion, type QueryMode, type QueryResult } from "../lib/api";

const starterQuestion =
  "Doanh nghiep can lam gi khi cap phat PPE cho nguoi lao dong theo tai lieu noi bo?";

const queryModes: { label: string; value: QueryMode }[] = [
  { label: "Tu dong", value: "auto" },
  { label: "Lookup", value: "lookup" },
  { label: "Summary", value: "summary" },
  { label: "Compare", value: "compare" },
  { label: "Temporal", value: "temporal" },
];

function answerTone(answerType: string) {
  return answerType === "grounded" || answerType === "partial" ? "status-ok" : "status-warn";
}

export function QueryPanel() {
  const [tenantId, setTenantId] = useState("tenant-demo");
  const [question, setQuestion] = useState(starterQuestion);
  const [mode, setMode] = useState<QueryMode>("auto");
  const [includeGraph, setIncludeGraph] = useState(true);
  const [includeSummaries, setIncludeSummaries] = useState(true);
  const [topK, setTopK] = useState(6);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  return (
    <section className="panel panel-strong">
      <div className="panel-header">
        <div>
          <h2>Truy Van RAG</h2>
          <p className="muted">
            Gui cau hoi qua gateway, xem answer type, citation va context duoc retrieval tra ve.
          </p>
        </div>
        <div className="pill">Gateway query flow</div>
      </div>

      <div className="input-grid">
        <input
          className="input"
          value={tenantId}
          onChange={(event) => setTenantId(event.target.value)}
          placeholder="Tenant ID"
        />
        <textarea
          className="textarea"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />

        <div className="query-controls">
          <label className="select-wrap">
            <span className="meta-label">query mode</span>
            <select
              className="input select"
              value={mode}
              onChange={(event) => setMode(event.target.value as QueryMode)}
            >
              {queryModes.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="select-wrap">
            <span className="meta-label">top k</span>
            <input
              className="input"
              type="number"
              min={1}
              max={12}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value) || 6)}
            />
          </label>

          <label className="toggle">
            <input
              type="checkbox"
              checked={includeGraph}
              onChange={() => setIncludeGraph((value) => !value)}
            />
            <span>Su dung graph evidence</span>
          </label>

          <label className="toggle">
            <input
              type="checkbox"
              checked={includeSummaries}
              onChange={() => setIncludeSummaries((value) => !value)}
            />
            <span>Cho phep summary contexts</span>
          </label>
        </div>

        <div className="button-row">
          <button
            className="button"
            disabled={isPending}
            type="button"
            onClick={() => {
              startTransition(() => {
                void (async () => {
                  try {
                    setError(null);
                    const next = await askQuestion({
                      tenantId,
                      question,
                      queryMode: mode,
                      topK,
                      includeGraph,
                      includeSummaries,
                    });
                    setResult(next);
                  } catch (nextError) {
                    setError(nextError instanceof Error ? nextError.message : "Unknown error");
                  }
                })();
              });
            }}
          >
            {isPending ? "Dang truy van..." : "Chay truy van"}
          </button>
          <button
            className="button ghost"
            type="button"
            onClick={() => {
              setTenantId("tenant-demo");
              setQuestion(starterQuestion);
              setMode("auto");
              setIncludeGraph(true);
              setIncludeSummaries(true);
              setTopK(6);
              setResult(null);
              setError(null);
            }}
          >
            Dat lai
          </button>
        </div>
      </div>

      <div className="answer-box">
        <div className="answer-header">
          <strong>Ket qua</strong>
          {result ? <div className={answerTone(result.answer_type)}>{result.answer_type}</div> : null}
        </div>

        {error ? (
          <div className="status-warn">{error}</div>
        ) : result ? (
          <>
            <div>{result.answer}</div>

            {result.clarification_question ? (
              <div className="callout">
                <strong>Clarification</strong>
                <p>{result.clarification_question}</p>
              </div>
            ) : null}

            {result.policy_summary.length > 0 ? (
              <div className="callout">
                <strong>Policy summary</strong>
                <ul className="flat-list">
                  {result.policy_summary.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="detail-grid">
              <div className="detail-card">
                <span className="meta-label">citations</span>
                <strong>{result.citations.length}</strong>
              </div>
              <div className="detail-card">
                <span className="meta-label">contexts</span>
                <strong>{result.contexts.length}</strong>
              </div>
              <div className="detail-card">
                <span className="meta-label">trace id</span>
                <strong className="tiny">{result.trace_id}</strong>
              </div>
            </div>

            <div className="list-box">
              <strong>Citations</strong>
              {result.citations.length === 0 ? (
                <div className="muted">Khong co citation nao duoc tra ve.</div>
              ) : (
                result.citations.map((citation) => (
                  <div className="citation-item" key={citation.chunk_id}>
                    <div>{citation.title}</div>
                    <div className="muted">
                      {citation.section || "unknown section"}
                      {citation.page ? ` | page ${citation.page}` : ""}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="list-box">
              <strong>Retrieved Contexts</strong>
              {result.contexts.map((context) => (
                <div className="context-item" key={context.chunk_id}>
                  <div className="context-head">
                    <strong>{context.source.title}</strong>
                    <span className="muted">
                      {context.retrieval_source} | score{" "}
                      {context.final_score?.toFixed(3) ?? context.score.toFixed(3)}
                    </span>
                  </div>
                  <div className="muted">{context.content.slice(0, 220)}...</div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="muted">Chua co ket qua. Hay gui mot cau hoi de test retrieval va answer policy.</div>
        )}
      </div>
    </section>
  );
}
