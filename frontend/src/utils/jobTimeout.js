export const isLongRunningJobError = (error) =>
  Boolean(error?.isLongRunningJob || error?.name === 'JobLongerThanExpectedError')

export const longRunningJobMessage = (error) =>
  error?.message ||
  'This is taking longer than usual — check Runs for progress.'
