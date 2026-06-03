export type IsbnLookupResponse = {
  found: boolean;
  isbn: string;
  title?: string;
  authors?: string[];
  publisher?: string;
  message?: string;
  metadata?: Record<string, unknown>;
};

export type ProcessStatusResponse = {
  status: "processing" | "done" | "error";
  progress: number;
  message: string;
  title?: string;
  fileName?: string;
};

export type BookRow = {
  id: string;
  title: string;
  createdAt: string;
  actions: string[];
  status: "processing" | "done" | "error";
};

export type PromptSettingsResponse = {
  prompt: string;
};
