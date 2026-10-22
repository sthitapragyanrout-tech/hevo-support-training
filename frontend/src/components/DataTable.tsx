import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Icon } from './Icon'
import styles from './DataTable.module.css'

export interface Column<Row> {
  key: string
  header: string
  render: (row: Row) => ReactNode
  /** Server-side sort key; sortable when set. */
  sort?: string
  align?: 'start' | 'end'
  /** Hidden below 600px so the table stays readable on a phone. */
  hideOnMobile?: boolean
}

export interface PageMeta {
  count: number
  page: number
  pages: number
  page_size: number
}

interface Props<Row> {
  /** Names the table for assistive technology. */
  label: string
  columns: Column<Row>[]
  rows: Row[]
  rowKey: (row: Row) => string | number
  /** Makes a row's first cell a link. */
  rowHref?: (row: Row) => string
  meta?: PageMeta
  ordering?: string
  onOrdering?: (ordering: string) => void
  onPage?: (page: number) => void
  /** Show a quiet "Updating…" without blanking the table. */
  busy?: boolean
  empty: ReactNode
}

/** The one table for every admin list: server-side paging and sorting, a
 * real <table> for screen readers, hairlines in place of boxes. */
export function DataTable<Row>({
  label,
  columns,
  rows,
  rowKey,
  rowHref,
  meta,
  ordering,
  onOrdering,
  onPage,
  busy,
  empty,
}: Props<Row>) {
  function toggle(sort: string) {
    onOrdering?.(ordering === sort ? `-${sort}` : sort)
  }

  if (rows.length === 0 && !busy) return <div className={styles.empty}>{empty}</div>

  const firstLink = columns[0]?.key
  return (
    <div className={styles.wrap} aria-busy={busy || undefined}>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <caption className="sr-only">{label}</caption>
          <thead>
            <tr>
              {columns.map((c) => {
                const active = c.sort && (ordering === c.sort || ordering === `-${c.sort}`)
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className={`${c.align === 'end' ? styles.end : ''} ${c.hideOnMobile ? styles.hideSm : ''}`}
                    aria-sort={
                      active ? (ordering?.startsWith('-') ? 'descending' : 'ascending') : undefined
                    }
                  >
                    {c.sort && onOrdering ? (
                      <button type="button" className={styles.sort} onClick={() => toggle(c.sort!)}>
                        {c.header}
                        {active && (
                          <Icon
                            name={ordering?.startsWith('-') ? 'arrowDown' : 'arrowUp'}
                            size={12}
                          />
                        )}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`${c.align === 'end' ? styles.end : ''} ${c.hideOnMobile ? styles.hideSm : ''}`}
                  >
                    {rowHref && c.key === firstLink ? (
                      <Link to={rowHref(row)} className={styles.link}>
                        {c.render(row)}
                      </Link>
                    ) : (
                      c.render(row)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {meta && meta.pages > 1 && (
        <nav className={styles.pager} aria-label="Pages">
          <span className={styles.count}>
            {meta.count} in total · page {meta.page} of {meta.pages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={meta.page <= 1}
            onClick={() => onPage?.(meta.page - 1)}
          >
            Previous
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={meta.page >= meta.pages}
            onClick={() => onPage?.(meta.page + 1)}
          >
            Next
          </button>
        </nav>
      )}
      {meta && meta.pages <= 1 && meta.count > 0 && (
        <p className={styles.count}>{meta.count === 1 ? '1 result' : `${meta.count} results`}</p>
      )}
    </div>
  )
}
