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

export type QueueItem = {
  id: string;
  title: string;
  isbn: string;
  status: string;
  stage: string;
  message: string;
  pageCount: number | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  estimatedDurationSeconds: number | null;
  estimatedStartAt: string | null;
  estimatedEndAt: string | null;
  queuePosition: number | null;
  canDownload: boolean;
  errorMessage: string | null;
};

export type QueueResponse = {
  tab: "open" | "finished" | string;
  items: QueueItem[];
  secondsPerPage: number;
  calibrationNote: string;
  error?: string;
};
