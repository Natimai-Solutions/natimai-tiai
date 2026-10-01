import { describe, expect, it } from 'vitest';

import {
  AUDIT_DEFAULT_PAGE_SIZE,
  auditListParams,
  auditPeriodParams,
  auditQueryFromState,
  auditStateFromQuery,
  emptyAuditFilters,
  hasAuditFilters,
  isAuditPeriodInverted,
  localDayEnd,
  localDayStart,
  readerTimeZone,
} from './auditQuery';

describe('localDayStart / localDayEnd', () => {
  it('reads midnight in the given zone, summer and winter time', () => {
    // Paris is UTC+2 in summer, UTC+1 in winter.
    expect(localDayStart('2026-07-14', 'Europe/Paris')).toBe('2026-07-13T22:00:00.000Z');
    expect(localDayStart('2026-01-15', 'Europe/Paris')).toBe('2026-01-14T23:00:00.000Z');
  });

  it('works behind UTC too', () => {
    // Tahiti, UTC−10 all year.
    expect(localDayStart('2026-09-01', 'Pacific/Tahiti')).toBe('2026-09-01T10:00:00.000Z');
  });

  it('is the identity in UTC', () => {
    expect(localDayStart('2026-09-01', 'UTC')).toBe('2026-09-01T00:00:00.000Z');
  });

  it('ends a day at the next midnight, across a month and a year', () => {
    expect(localDayEnd('2026-09-30', 'Europe/Paris')).toBe('2026-09-30T22:00:00.000Z');
    expect(localDayEnd('2026-12-31', 'UTC')).toBe('2027-01-01T00:00:00.000Z');
  });

  // 25 October 2026 is the night Paris goes back to UTC+1: the day lasts 25 h.
  it('spans a DST change correctly', () => {
    expect(localDayStart('2026-10-25', 'Europe/Paris')).toBe('2026-10-24T22:00:00.000Z');
    expect(localDayEnd('2026-10-25', 'Europe/Paris')).toBe('2026-10-25T23:00:00.000Z');
  });

  it('settles a day whose offset changes between the guess and midnight', () => {
    // 29 March 2026: Paris moves to UTC+2 at 02:00 local; midnight is still UTC+1.
    expect(localDayStart('2026-03-29', 'Europe/Paris')).toBe('2026-03-28T23:00:00.000Z');
    expect(localDayEnd('2026-03-28', 'Europe/Paris')).toBe('2026-03-28T23:00:00.000Z');
  });

  it('refuses what is not a calendar day', () => {
    expect(localDayStart('2026-02-30', 'UTC')).toBeNull();
    expect(localDayStart('30/09/2026', 'UTC')).toBeNull();
    expect(localDayEnd('', 'UTC')).toBeNull();
  });
});

describe('auditPeriodParams', () => {
  it('includes the whole last day', () => {
    expect(auditPeriodParams('2026-09-01', '2026-09-30', 'Europe/Paris')).toEqual({
      since: '2026-08-31T22:00:00.000Z',
      until: '2026-09-30T22:00:00.000Z',
    });
  });

  it('leaves out an absent or malformed bound', () => {
    expect(auditPeriodParams(null, '2026-09-30', 'UTC')).toEqual({
      until: '2026-10-01T00:00:00.000Z',
    });
    expect(auditPeriodParams('nope', null, 'UTC')).toEqual({});
  });
});

describe('isAuditPeriodInverted', () => {
  it('flags an end before the start only', () => {
    expect(isAuditPeriodInverted('2026-09-30', '2026-09-01')).toBe(true);
    expect(isAuditPeriodInverted('2026-09-01', '2026-09-01')).toBe(false);
    expect(isAuditPeriodInverted('2026-09-01', null)).toBe(false);
  });
});

describe('auditStateFromQuery / auditQueryFromState', () => {
  it('reads an empty URL as no filter, first page, default size', () => {
    expect(auditStateFromQuery({})).toEqual({
      filters: emptyAuditFilters(),
      page: 1,
      pageSize: AUDIT_DEFAULT_PAGE_SIZE,
    });
  });

  it('round-trips every filter and the page', () => {
    const query = {
      action: 'machine.merge',
      actor: 'marie',
      resource_type: 'machine',
      resource_id: 'abc',
      from: '2026-09-01',
      to: '2026-09-30',
      page: '3',
      page_size: '100',
    };
    const state = auditStateFromQuery(query);
    expect(state.filters).toEqual({
      action: 'machine.merge',
      actor: 'marie',
      resourceType: 'machine',
      resourceId: 'abc',
      from: '2026-09-01',
      to: '2026-09-30',
    });
    expect(auditQueryFromState(state)).toEqual(query);
  });

  // A hand-edited URL degrades to a broader search, never to a 422.
  it('drops malformed values', () => {
    const state = auditStateFromQuery({ from: '2026-13-01', page: '-2', page_size: '7' });
    expect(state.filters.from).toBeNull();
    expect(state.page).toBe(1);
    expect(state.pageSize).toBe(AUDIT_DEFAULT_PAGE_SIZE);
  });

  it('omits defaults from the URL', () => {
    expect(
      auditQueryFromState({
        filters: { ...emptyAuditFilters(), actor: '  ' },
        page: 1,
        pageSize: AUDIT_DEFAULT_PAGE_SIZE,
      }),
    ).toEqual({});
  });
});

describe('hasAuditFilters', () => {
  it('tells an empty search from a filtered one', () => {
    expect(hasAuditFilters(emptyAuditFilters())).toBe(false);
    expect(hasAuditFilters({ ...emptyAuditFilters(), actor: ' ' })).toBe(false);
    expect(hasAuditFilters({ ...emptyAuditFilters(), to: '2026-09-30' })).toBe(true);
  });
});

describe('auditListParams', () => {
  it('builds the API params, period in the given zone', () => {
    expect(
      auditListParams(
        {
          filters: {
            action: 'user.create',
            actor: ' marie ',
            resourceType: 'user',
            resourceId: 'u-1',
            from: '2026-09-01',
            to: '2026-09-01',
          },
          page: 2,
          pageSize: 25,
        },
        'Pacific/Tahiti',
      ),
    ).toEqual({
      action: 'user.create',
      actor: 'marie',
      resource_type: 'user',
      resource_id: 'u-1',
      since: '2026-09-01T10:00:00.000Z',
      until: '2026-09-02T10:00:00.000Z',
      page: 2,
      page_size: 25,
    });
  });

  it('sends only the pagination without filters', () => {
    expect(auditListParams({ filters: emptyAuditFilters(), page: 1, pageSize: 50 }, 'UTC')).toEqual(
      { page: 1, page_size: 50 },
    );
  });
});

describe('readerTimeZone', () => {
  it('answers an IANA zone name', () => {
    expect(typeof readerTimeZone()).toBe('string');
    expect(readerTimeZone().length).toBeGreaterThan(0);
  });
});
