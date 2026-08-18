/**
 * Follow-up questions about the current analysis.
 *
 * The backend answers from the same analytical context the report was built
 * from — this is not a natural-language query engine.
 */

import { useState, type FormEvent } from 'react';

import { askAnalyst } from '@/api/aiAnalyst';
import { Card, ErrorState, Spinner } from '@/components/ui';
import type { AnalystAnswer } from '@/types/api';

interface AskAnalystProps {
  projectId: string;
  datasetId: string;
  versionId?: string;
  aiAvailable: boolean;
  aiStatus: string | null;
}

const EXAMPLES = [
  'Which category performs best?',
  'What are the biggest risks in this data?',
  'Which period had the highest revenue?',
  'Where is performance weakest?',
];

export function AskAnalyst({
  projectId,
  datasetId,
  versionId,
  aiAvailable,
  aiStatus,
}: AskAnalystProps) {
  const [question, setQuestion] = useState('');
  const [answers, setAnswers] = useState<AnalystAnswer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (trimmed.length < 3) return;

    setBusy(true);
    setError(null);
    try {
      const answer = await askAnalyst(projectId, datasetId, trimmed, versionId);
      setAnswers((current) => [answer, ...current]);
      setQuestion('');
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Ask the AI analyst">
      {!aiAvailable && (
        <p className="muted small" data-testid="ask-unavailable">
          {aiStatus ??
            'No AI provider is configured, so follow-up questions are unavailable.'}{' '}
          The insights on this page were computed without AI and still apply.
        </p>
      )}

      <form onSubmit={submit} className="stack" noValidate>
        <label className="field">
          <span className="muted small">Your question</span>
          <input
            className="input"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="e.g. Which region is underperforming?"
            aria-label="Question for the AI analyst"
            disabled={!aiAvailable || busy}
          />
        </label>

        <div className="row">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="button button--ghost"
              onClick={() => setQuestion(example)}
              disabled={!aiAvailable || busy}
            >
              {example}
            </button>
          ))}
        </div>

        <button
          type="submit"
          className="button"
          disabled={!aiAvailable || busy || question.trim().length < 3}
        >
          {busy ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {busy && <Spinner label="Consulting the analyst…" />}
      {error && <ErrorState error={error} />}

      {answers.length > 0 && (
        <ul className="list list--plain" data-testid="analyst-answers">
          {answers.map((answer, index) => (
            <li key={`${answer.question}-${index}`} className="insight">
              <p>
                <strong>{answer.question}</strong>
              </p>
              <p className="muted">{answer.answer}</p>
              {answer.contains_untraceable_numbers && (
                <p className="field__error small" role="note">
                  Some figures in this answer could not be matched to the computed
                  analysis — verify them against the insights above.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
