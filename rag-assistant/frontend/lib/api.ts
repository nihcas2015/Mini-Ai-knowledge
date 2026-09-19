/**
 * Frontend API client with Next.js proxy support to prevent HTTPS Mixed-Content blocking.
 */

function getApiUrl(): string {
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    return '/api/backend';
  }
  return process.env.NEXT_PUBLIC_API_URL || 'http://65.2.69.137:8000';
}

export async function createSession(): Promise<string> {
  const res = await fetch(`${getApiUrl()}/session`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to create session: ${res.statusText}`);
  const data = await res.json();
  return data.session_id;
}

export async function uploadDocument(sessionId: string, file: File) {
  const formData = new FormData();
  formData.append('session_id', sessionId);
  formData.append('file', file);

  const res = await fetch(`${getApiUrl()}/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    let errorMessage = 'Failed to upload document';
    try {
      const errorData = await res.json();
      if (errorData.detail) errorMessage = errorData.detail;
    } catch (e) {
      // Ignored if json parse fails
    }
    throw new Error(errorMessage);
  }
  return res.json();
}

export async function clearDocuments(sessionId: string) {
  const res = await fetch(`${getApiUrl()}/session/${sessionId}/documents`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to clear documents');
  return res.json();
}

export async function endSession(sessionId: string) {
  const res = await fetch(`${getApiUrl()}/session/${sessionId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to end session');
  return res.json();
}

export interface Citation {
  marker: number;
  filename: string;
  page_number: number;
  source_type: 'base' | 'user';
  snippet: string;
}

export interface AskResult {
  answer: string;
  citations: Citation[];
  provider_used: string;
}

export type SourceFilter = 'base' | 'user' | 'both';

export async function askQuestion(
  sessionId: string,
  question: string,
  sourceFilter: SourceFilter,
  onToken: (token: string) => void,
  onFinish: (result: AskResult) => void,
  onError: (error: Error) => void
) {
  try {
    const res = await fetch(`${getApiUrl()}/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        question,
        source_filter: sourceFilter,
      }),
    });

    if (!res.ok) {
      throw new Error(`API error: ${res.status}`);
    }

    if (!res.body) throw new Error('No readable stream');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6).trim();
          if (dataStr === '[DONE]') continue;

          try {
            const data = JSON.parse(dataStr);

            if (data.type === 'token' && data.content) {
              onToken(data.content);
            } else if (data.type === 'final' && data.data) {
              onFinish(data.data as AskResult);
            } else if (data.type === 'error' && data.content) {
              onError(new Error(data.content));
            }
          } catch (e) {
            // Skip malformed JSON
          }
        }
      }
    }
  } catch (err) {
    onError(err instanceof Error ? err : new Error(String(err)));
  }
}
