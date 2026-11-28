"use strict";

/**
 * GitHub-only scheduler controller.
 * The workflow invokes this module every five minutes; this module never uses
 * Google Apps Script or Google Sheets to decide when a scan should run.
 */
module.exports = async function runScheduler({ github, context, core }) {
  const { owner, repo } = context.repo;
  const response = await github.rest.actions.listWorkflowRuns({
    owner,
    repo,
    workflow_id: "auto_scan.yml",
    branch: "main",
    per_page: 30
  });
  const runs = response.data.workflow_runs
    .filter(run => run.id !== context.runId)
    .slice(0, 30);
  
  // One GitHub controller owns both schedules. It never dispatches
  // while any scan job is queued/running, and measures cooldown from
  // the job's completed_at timestamp (not the dispatch/start time).
  const jobResults = await Promise.all(runs.map(async run => {
    const result = await github.rest.actions.listJobsForWorkflowRun({
      owner, repo, run_id: run.id, per_page: 30
    });
    return { run, jobs: result.data.jobs };
  }));
  
  const scanJobs = [];
  for (const entry of jobResults) {
    for (const job of entry.jobs) {
      if (job.name === "priority-scan" || job.name === "scan") {
        scanJobs.push({
          run: entry.run,
          job,
          profile: job.name === "priority-scan" ? "priority" : "full"
        });
      }
    }
  }
  
  const now = Date.now();
  const activeJobs = scanJobs.filter(({ job }) =>
    ["queued", "pending", "in_progress"].includes(job.status)
  );
  const stale = activeJobs.find(({ run, job, profile }) => {
    const reference = job.status === "in_progress"
      ? (job.started_at || run.run_started_at || run.created_at)
      : run.created_at;
    const age = (now - Date.parse(reference)) / 60000;
    const limit = job.status === "in_progress"
      ? (profile === "priority" ? 15 : 50)
      : 20;
    return Number.isFinite(age) && age > limit;
  });
  
  let action = "WAIT_ACTIVE";
  let reason = "";
  let dispatchedProfile = "";
  let priorityAge = null;
  let fullAge = null;
  if (stale) {
    await github.rest.actions.cancelWorkflowRun({
      owner, repo, run_id: stale.run.id
    });
    action = "CANCEL_STALE";
    reason = `Cancelled stale ${stale.profile} run #${stale.run.run_number}; re-evaluate on next controller tick`;
    core.warning(reason);
  } else if (activeJobs.length) {
    const active = activeJobs[0];
    action = "WAIT_ACTIVE";
    reason = `${active.profile} run #${active.run.run_number} is ${active.job.status}; no duplicate dispatch`;
    core.info(reason);
  } else {
    const latestCompleted = profile => scanJobs
      .filter(row => row.profile === profile && row.job.completed_at)
      .sort((a, b) => Date.parse(b.job.completed_at) - Date.parse(a.job.completed_at))[0] || null;
  
    const priorityLast = latestCompleted("priority");
    const fullLast = latestCompleted("full");
    priorityAge = priorityLast ? (now - Date.parse(priorityLast.job.completed_at)) / 60000 : Number.POSITIVE_INFINITY;
    fullAge = fullLast ? (now - Date.parse(fullLast.job.completed_at)) / 60000 : Number.POSITIVE_INFINITY;
    // Priority repeats no sooner than 5 minutes after completion.
    // Full retains its 30-minute cadence; after a failed full scan,
    // retry after a 5-minute post-completion cooldown.
    const priorityDue = priorityAge >= 5;
    const fullRetryDue = Boolean(fullLast && fullLast.job.conclusion !== "success" && fullAge >= 5);
    const fullDue = fullAge >= 30;
    const latestAnyCompleted = scanJobs
      .filter(row => row.job.completed_at)
      .sort((a, b) => Date.parse(b.job.completed_at) - Date.parse(a.job.completed_at))[0] || null;
    const globalCooldownAge = latestAnyCompleted
      ? (now - Date.parse(latestAnyCompleted.job.completed_at)) / 60000
      : Number.POSITIVE_INFINITY;
  
    if (globalCooldownAge < 5) {
      action = "POST_COMPLETION_COOLDOWN";
      reason = `Last scan completed ${Math.round(globalCooldownAge)}m ago; wait until 5 minutes after completion`;
    } else if (fullDue) {
      dispatchedProfile = "full_only";
      action = "DISPATCH_FULL";
      reason = `30-minute full-scan cadence reached; last full completion: ${Number.isFinite(fullAge) ? Math.round(fullAge) + "m ago" : "not found"}`;
    } else if (priorityDue) {
      dispatchedProfile = "priority_only";
      action = "DISPATCH_PRIORITY";
      reason = `No active scan; last priority completion: ${Number.isFinite(priorityAge) ? Math.round(priorityAge) + "m ago" : "not found"}`;
    } else if (fullRetryDue) {
      dispatchedProfile = "full_only";
      action = "DISPATCH_FULL";
      reason = `Retrying failed full scan after cooldown; last full completion: ${Math.round(fullAge)}m ago`;
    } else {
      action = "COOLDOWN";
      reason = `Priority completed ${Math.round(priorityAge)}m ago; full completed ${Math.round(fullAge)}m ago`;
    }
  
    if (dispatchedProfile) {
      await github.rest.actions.createWorkflowDispatch({
        owner, repo, workflow_id: "auto_scan.yml", ref: "main",
        inputs: { profile: dispatchedProfile }
      });
      core.info(`GitHub accepted ${dispatchedProfile}; next controller tick verifies job creation.`);
    }
  }
  
  await core.summary
    .addHeading("Trạm Tin Tức – Bộ điều phối GitHub")
    .addTable([
      [{data: "Thông tin", header: true}, {data: "Giá trị", header: true}],
      ["Hành động", action],
      ["Lý do", reason],
      ["Lượt được gửi", dispatchedProfile || "Không gửi lệnh"],
      ["Tuổi lượt ưu tiên (phút)", Number.isFinite(priorityAge) ? String(Math.round(priorityAge)) : "Chưa có"],
      ["Tuổi lượt toàn bộ (phút)", Number.isFinite(fullAge) ? String(Math.round(fullAge)) : "Chưa có"],
      ["Job đang hoạt động", String(activeJobs.length)]
    ])
    .write();
  core.info(`Scheduler decision: ${action}. ${reason}`);
};
