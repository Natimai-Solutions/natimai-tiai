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
      status: 'outdated',
      wu_status: 'pending',
      with_active_threats: 'true',
      sort_by: 'hostname',
      sort_desc: 'false',
    });

    expect(params).toEqual({
      search: 'pc-01',
      domain: 'CORP',
      antivirus: 'ESET',
      status: 'outdated',
      wu_status: 'pending',
      with_active_threats: true,
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
      sort_by: 'hashed_password',
    });

    expect(params).toEqual({});
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
});

describe('shared page-size defaults', () => {
  it('is one of the offered options, so a rebuilt URL is always valid', () => {
    // The list writes `page_size` only when it differs from the default, and the
    // fiche divides a rank by that same default to find the return page. A
    // default outside the options would put the two readings out of step.
    expect(PAGE_SIZE_OPTIONS).toContain(DEFAULT_PAGE_SIZE);
  });
});
