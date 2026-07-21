export function eventsToTraces(events = []) {
  const sessions = {}
  for (const event of events) {
    const sessionId = event.session_id || 'unknown'
    if (!sessions[sessionId]) {
      sessions[sessionId] = {
        sessionId,
        taskId: event.task_id,
        phase: event.snapshot_phase,
        variantId: event.snapshot_phase,
        customerId: event.task_id,
        outcome: 'in_progress',
        events: []
      }
    }
    sessions[sessionId].events.push({
      ...event,
      event_type: event.action || event.event_type
    })
  }
  for (const trace of Object.values(sessions)) {
    const ordered = trace.events
    const last = ordered[ordered.length - 1]
    if (last?.action === 'TASK_SUCCESS' || last?.success) trace.outcome = 'success'
    else if (last?.action === 'EXIT') trace.outcome = 'blocked'
    else trace.outcome = 'incomplete'
  }
  return Object.values(sessions)
}
