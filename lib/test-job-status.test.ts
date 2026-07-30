import assert from "node:assert/strict";
import { describe, it } from "node:test";

type JobLike = {
  id: string;
  status: string;
  filename: string;
  total_pages: number;
  total_figures: number;
  processed_pages: number;
  failed_pages: number;
  processed_figures: number;
  failed_figures: number;
  prompt_hash: string;
  error_message: string | null;
};

function mapTestJobToStatus(job: JobLike) {
  const stats = {
    pages: job.total_pages,
    figures: job.total_figures,
    processedPages: job.processed_pages,
    failedPages: job.failed_pages,
    processedFigures: job.processed_figures,
    failedFigures: job.failed_figures,
  };

  if (job.status === "done") {
    return {
      status: "done" as const,
      progress: 100,
      message: "ok",
      promptHash: job.prompt_hash,
      stats,
    };
  }
  if (job.status === "failed") {
    return {
      status: "error" as const,
      progress: 0,
      message: job.error_message || "fail",
      promptHash: job.prompt_hash,
      stats,
    };
  }
  const totalUnits = Math.max(1, job.total_pages + job.total_figures);
  const doneUnits = job.processed_pages + job.processed_figures + job.failed_pages + job.failed_figures;
  const progress = Math.min(95, Math.max(5, Math.round((doneUnits / totalUnits) * 100)));
  return {
    status: "processing" as const,
    progress,
    message: "running",
    promptHash: job.prompt_hash,
    stats,
  };
}

describe("mapTestJobToStatus", () => {
  it("mapeia done / failed / running", () => {
    const done = mapTestJobToStatus({
      id: "1",
      status: "done",
      filename: "livro.pdf",
      total_pages: 2,
      total_figures: 1,
      processed_pages: 2,
      failed_pages: 0,
      processed_figures: 1,
      failed_figures: 0,
      prompt_hash: "abc",
      error_message: null,
    });
    assert.equal(done.status, "done");
    assert.equal(done.progress, 100);

    const failed = mapTestJobToStatus({
      id: "2",
      status: "failed",
      filename: "livro.pdf",
      total_pages: 2,
      total_figures: 0,
      processed_pages: 0,
      failed_pages: 2,
      processed_figures: 0,
      failed_figures: 0,
      prompt_hash: "abc",
      error_message: "boom",
    });
    assert.equal(failed.status, "error");
    assert.match(failed.message, /boom/);

    const running = mapTestJobToStatus({
      id: "3",
      status: "running",
      filename: "livro.pdf",
      total_pages: 10,
      total_figures: 10,
      processed_pages: 5,
      failed_pages: 0,
      processed_figures: 2,
      failed_figures: 0,
      prompt_hash: "abc",
      error_message: null,
    });
    assert.equal(running.status, "processing");
    assert.ok(running.progress >= 5 && running.progress <= 95);
  });
});
