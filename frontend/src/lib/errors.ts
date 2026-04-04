/**
 * Typed API error hierarchy for distinguishing error types in UI and retry logic.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public code?: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

export class AuthError extends ApiError {
  constructor(detail: string) {
    super(401, detail)
    this.name = 'AuthError'
  }
}

export class NotFoundError extends ApiError {
  constructor(detail: string) {
    super(404, detail)
    this.name = 'NotFoundError'
  }
}

export class ConflictError extends ApiError {
  constructor(detail: string) {
    super(409, detail)
    this.name = 'ConflictError'
  }
}

export class ValidationError extends ApiError {
  constructor(detail: string) {
    super(422, detail)
    this.name = 'ValidationError'
  }
}

export class RateLimitError extends ApiError {
  constructor(detail: string = 'Too many requests. Please try again later.') {
    super(429, detail)
    this.name = 'RateLimitError'
  }
}

export class PayloadTooLargeError extends ApiError {
  constructor(detail: string = 'File too large.') {
    super(413, detail)
    this.name = 'PayloadTooLargeError'
  }
}
