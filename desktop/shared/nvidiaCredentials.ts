export interface NvidiaCredentialStatus {
  configured: boolean;
  source: "app" | "environment" | "none";
  hasStoredKey: boolean;
  storageAvailable: boolean;
  error: string;
  keys: ReadonlyArray<{ id: string; label: string }>;
  defaultKeyId: string;
  modelBindings: Readonly<Record<string, string>>;
}

export interface NvidiaCredentialOptions {
  id?: string;
  label: string;
}
