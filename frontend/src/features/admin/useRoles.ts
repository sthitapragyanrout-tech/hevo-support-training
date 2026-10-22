import { adminApi, type RoleOption } from './adminApi'
import { useQuery } from './useQuery'

/** The roles that exist (built-in and added), for pickers and labels. */
export function useRoleOptions(): { options: RoleOption[]; label: (name: string) => string } {
  const { data } = useQuery(() => adminApi.roleOptions(), 'role-options')
  const options = data?.results ?? []
  const byName = new Map(options.map((o) => [o.name, o.label]))
  // Until the list arrives (or for a role since removed) fall back to the key.
  return { options, label: (name) => byName.get(name) ?? name.replace(/_/g, ' ') }
}
