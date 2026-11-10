export interface ClaudeCredentialStatus {
  source: "app" | "environment" | "none";
  hasStoredKey: boolean;
  storageAvailable: boolean;
  error: string;
}
