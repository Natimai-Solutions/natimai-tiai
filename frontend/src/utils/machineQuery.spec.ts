import { describe, expect, it } from 'vitest';
import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  machineListParamsFromQuery,
  queryValue,
} from './machineQuery';

describe('queryValue', () => {
  it('reads a scalar and drops an array’s extra values', () => {
    expect(queryValue('outdated')).toBe('outdated');
    expect(queryValue(['first', 'second'])).toBe('first');
  });

  it('treats absent and empty as absent', () => {
    expect(queryValue(undefined)).toBeNull();
    expect(queryValue('')).toBeNull();
    expect(queryValue(null)).toBeNull();
  });
});

describe('machineListParamsFromQuery', () => {
  it('carries the whole search across a navigation', () => {
    const params = machineListParamsFromQuery({
      search: 'pc-01',
      domain: 'CORP',
      antivirus: 'ESET',
      os_version: 'Windows 11 23H2',
      status: 'outdated',
      wu_status: 'pending',
      scan_type: 'quick',
      scan_days: '30',
      with_active_threats: 'true',
      online: 'true',
      sort_by: 'hostname',
      sort_desc: 'false',
    });

    expect(params).toEqual({
      search: 'pc-01',
      domain: 'CORP',
      antivirus: 'ESET',
      os_version: 'Windows 11 23H2',
      status: 'outdated',
      wu_status: 'pending',
      scan_type: 'quick',
      scan_older_than_days: 30,
      with_active_threats: true,
      online: true,
      sort_by: 'hostname',
      sort_desc: false,
    });
  });

  it('omits everything an empty URL does not carry', () => {
    expect(machineListParamsFromQuery({})).toEqual({});
  });

  it('drops values it does not recognise rather than forwarding them', () => {
    // A hand-edited URL must degrade to a broader search, not to a 422.
    const params = machineListParamsFromQuery({
      status: 'on-fire',
      wu_status: 'whenever',
      scan_type: 'deep',
      sort_by: 'hashed_password',
    });

    expect(params).toEqual({});
  });

  it('falls back to a week when the scan age is missing or hand-edited', () => {
    expect(machineListParamsFromQuery({ scan_type: 'full' })).toEqual({
      scan_type: 'full',
      scan_older_than_days: 7,
    });
    expect(machineListParamsFromQuery({ scan_type: 'full', scan_days: '9999' })).toEqual({
      scan_type: 'full',
      scan_older_than_days: 7,
    });
  });

  it('ignores a scan age with no scan type to apply it to', () => {
    expect(machineListParamsFromQuery({ scan_days: '30' })).toEqual({});
  });

  it('defaults a sort to descending, as the table does', () => {
    const params = machineListParamsFromQuery({ sort_by: 'last_seen' });

    expect(params.sort_by).toBe('last_seen');
    expect(params.sort_desc).toBe(true);
  });

  it('only enables the threat filter on an explicit true', () => {
    expect(machineListParamsFromQuery({ with_active_threats: 'false' })).toEqual({});
    expect(machineListParamsFromQuery({ with_active_threats: '1' })).toEqual({});
  });

  it('only enables the online filter on an explicit true', () => {
    // The toggle only ever writes `online=true`; anything else in a URL is
    // hand-edited and degrades to the unfiltered list.
    expect(machineListParamsFromQuery({ online: 'false' })).toEqual({});
    expect(machineListParamsFromQuery({ online: '1' })).toEqual({});
  });
});

describe('machineListParamsFromQuery inventory facets', () => {
  it('carries the hardware facets the list page writes', () => {
    // The fiche walks the search with these; a facet dropped here would have
    // the arrows walk a broader list than the one the reader came from.
    const params = machineListParamsFromQuery({
      hw_model: 'OptiPlex',
      hw_manufacturer: 'Dell',
      cpu_model: 'i5-8',
      hw_chassis_type: 'laptop',
      ram_min_gb: '8',
      ram_max_gb: '16',
      disk_free_below: '10',
      software_id: '42',
    });

    expect(params).toEqual({
      hw_model: 'OptiPlex',
      hw_manufacturer: 'Dell',
      cpu_model: 'i5-8',
      hw_chassis_type: 'laptop',
      ram_min_gb: 8,
      ram_max_gb: 16,
      disk_free_below: 10,
      software_id: 42,
    });
  });

  it('drops numbers that do not parse and kinds it does not know', () => {
    expect(
      machineListParamsFromQuery({
        hw_chassis_type: 'spaceship',
        ram_min_gb: 'lots',
        ram_max_gb: '-3',
        disk_free_below: '250',
        software_id: '1.5',
      }),
    ).toEqual({});
  });

  it('accepts the inventory sort columns', () => {
    expect(
      machineListParamsFromQuery({ sort_by: 'disk_free_percent', sort_desc: 'false' }),
    ).toEqual({ sort_by: 'disk_free_percent', sort_desc: false });
  });
});

describe('shared page-size defaults', () => {
  it('is one of the offered options, so a rebuilt URL is always valid', () => {
    // The list writes `page_size` only when it differs from the default, and the
    // fiche divides a rank by that same default to find the return page. A
    // default outside the options would put the two readings out of step.
    expect(PAGE_SIZE_OPTIONS).toContain(DEFAULT_PAGE_SIZE);
  });
});

describe('machineListParamsFromQuery — agent facet', () => {
  it('carries an exact version and the "behind" flag', () => {
    expect(machineListParamsFromQuery({ agent_version: '0.4.1' })).toEqual({
      agent_version: '0.4.1',
    });
    expect(machineListParamsFromQuery({ agent_outdated: 'true' })).toEqual({
      agent_outdated: true,
    });
  });

  it('drops anything but "true" for the flag', () => {
    expect(machineListParamsFromQuery({ agent_outdated: 'yes' })).toEqual({});
  });
});
