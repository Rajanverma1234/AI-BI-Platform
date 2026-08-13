/** Health endpoints. Feature-specific API modules live alongside this one. */

import { apiClient } from '@/lib/apiClient';
import type { HealthResponse, ReadinessResponse } from '@/types/api';

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiClient.get<HealthResponse>('/health', signal ? { signal } : {});
}

export function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return apiClient.get<ReadinessResponse>('/health/ready', signal ? { signal } : {});
}
