import type { ApiErrorBody, ApiErrorCode } from '@study-league/shared-types';

/**
 * A structured API failure.
 *
 * Carrying the stable `code` means UI can react to specific situations (an active session
 * elsewhere, a stale settings version) without string-matching messages that may be
 * translated or reworded.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode | 'network_error' | 'unknown_error';
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: ApiError['code'],
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when retrying later could plausibly succeed. */
  get isRetryable(): boolean {
    return (
      this.code === 'network_error' ||
      this.status === 429 ||
      (this.status >= 500 && this.status < 600)
    );
  }

  /** True when the caller should re-authenticate. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  static fromResponse(status: number, body: unknown): ApiError {
    const parsed = body as Partial<ApiErrorBody> | null;
    if (parsed && typeof parsed === 'object' && parsed.error) {
      return new ApiError(
        status,
        parsed.error.code,
        parsed.error.message,
        parsed.error.details ?? {},
      );
    }
    return new ApiError(status, 'unknown_error', 'An unexpected error occurred.');
  }

  static network(cause: unknown): ApiError {
    const message = cause instanceof Error ? cause.message : 'Network request failed';
    return new ApiError(0, 'network_error', message);
  }
}
