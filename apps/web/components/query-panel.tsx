"use client";

import { useState, useTransition } from "react";

import { askQuestion, type QueryResult } from "../lib/api";

const starterQuestion =
  "Doanh nghiệp có nghĩa vụ gì khi cấp phát PPE cho người lao động?";

export function QueryPanel() {
  const [question, setQuestion] = useState(starterQuestion);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Grounded Answer Console</h2>
          <p className="muted">
            Route a live query through the gateway and inspect answer plus citations.
          </p>
        </div>
        <div className="pill">Tenant-safe stub flow</div>
      </div>

      <div className="input-grid">
        <textarea
          className="textarea"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="button-row">
          <button
            className="button"
            disabled={isPending}
            onClick={() => {
              startTransition(() => {
                void (async () => {
                  try {
                    setError(null);
                    const next = await askQuestion(question);
                    setResult(next);
                  } catch (nextError) {
                    setError(nextError instanceof Error ? nextError.message : "Unknown error");
                  }
                })();
              });
            }}
          >
            {isPending ? "Running query..." : "Run grounded query"}
          </button>
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              setQuestion(starterQuestion);
              setResult(null);
              setError(null);
            }}
          >
            Reset
          </button>
        </div>
      </div>

      <div className="answer-box" style={{ marginTop: 18 }}>
        <strong>Answer</strong>
        {error ? (
          <div className="status-warn">{error}</div>
        ) : result ? (
          <>
            <div>{result.answer}</div>
            <div className="list-box">
              <strong>Citations</strong>
              {result.citations.map((citation) => (
                <div className="citation-item" key={citation.chunk_id}>
                  <div>{citation.title}</div>
                  <div className="muted">
                    {citation.section}
                    {citation.page ? ` · page ${citation.page}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="muted">No answer yet. Submit a question to test the orchestration.</div>
        )}
      </div>
    </section>
  );
}
