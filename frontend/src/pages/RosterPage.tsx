import type { Driver, Location } from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import { PageHead, Panel } from '../components/ui'

/**
 * Phase 10 (the duty builder) is not implemented in this build. Drivers are,
 * because they are reference data the rest of the system wants regardless.
 *
 * The API contract for duties is already fixed — /duties, /duties/{id}/pieces
 * and /duties/{id}/validate exist with their final request and response
 * models and return 501 — so the builder can be added without any client
 * rework.
 */
export default function RosterPage() {
  const { items: locations } = useList<Location>('/locations')

  return (
    <>
      <PageHead
        title="Roster"
        intro="Drivers, and the duty builder that will assign block pieces to them."
      />

      <Panel title="Duty builder">
        <div className="alert info" style={{ marginBottom: 0 }}>
          <strong>Not in this build.</strong>
          <p style={{ margin: '6px 0 0' }}>
            Building duties from finished blocks — splitting a block between an
            AM and a PM driver, inserting breaks, live-checking against the
            operating parameters — is phase 10.
          </p>
          <p style={{ margin: '6px 0 0' }}>
            The groundwork is in place: the <code>duties</code> and{' '}
            <code>duty_pieces</code> tables exist, the operating parameters on
            the Settings page are live, and the endpoints are published with
            their final shapes (they answer <code>501</code> today). Everything
            it depends on — blocks with real location continuity — is finished.
          </p>
        </div>
      </Panel>

      <Panel title="Drivers">
        <CrudTable<Driver>
          endpoint="/drivers"
          entityName="Driver"
          columns={[
            { key: 'code', label: 'Code' },
            { key: 'display_name', label: 'Name' },
            { key: 'base_location_name', label: 'Base' },
            { key: 'phone', label: 'Phone' },
            { key: 'email', label: 'Email' },
            {
              key: 'is_active',
              label: 'Status',
              render: (row) =>
                row.is_active ? (
                  <span className="tag ok">active</span>
                ) : (
                  <span className="tag grey">inactive</span>
                ),
            },
          ]}
          fields={[
            { name: 'code', label: 'Staff code', required: true },
            { name: 'first_name', label: 'First name', required: true },
            { name: 'last_name', label: 'Last name', required: true },
            {
              name: 'base_location_id',
              label: 'Base depot',
              type: 'select',
              options: locations
                .filter((l) => ['depot', 'garage'].includes(l.location_type))
                .map((l) => ({ value: l.id, label: l.name })),
            },
            { name: 'phone', label: 'Phone' },
            { name: 'email', label: 'Email' },
            { name: 'is_active', label: 'Active', type: 'checkbox' },
            { name: 'notes', label: 'Notes', type: 'textarea' },
          ]}
          defaults={{ is_active: true }}
        />
      </Panel>
    </>
  )
}
