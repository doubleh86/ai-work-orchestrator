export interface ChatControlView {
  projectName: string;
  runId: string;
  requestId: string;
  intent: string;
  phase: string;
  status: string;
  error: string;
  startedAt: number;
}
