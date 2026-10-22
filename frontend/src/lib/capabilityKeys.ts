/** Known actions (mirrors backend `accounts.rbac.KNOWN_ACTIONS`). The server
 * decides what each user may do and reports it in the session; the UI only
 * uses this to decide what to *show* — every endpoint still enforces. */
export const CAN = {
  authorContent: 'catalog.author_content',
  publishCourse: 'catalog.publish_courseversion',
  manageUsers: 'accounts.manage_users',
  manageRoles: 'accounts.manage_roles',
  viewResults: 'progress.view_results',
  manageAttempts: 'progress.manage_attempts',
  viewAudit: 'audit.view_audit',
} as const
