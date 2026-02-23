.headers on
.mode column

-- Latest meeting + one approved member in that band
WITH latest_meeting AS (
  SELECT id AS meeting_id, band_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
),
probe_user AS (
  SELECT m.user_id
  FROM pracapp_membership m
  JOIN latest_meeting lm ON lm.band_id = m.band_id
  WHERE m.is_approved = 1
  ORDER BY m.rowid ASC
  LIMIT 1
)
SELECT 'meeting_id' AS k, meeting_id AS v FROM latest_meeting
UNION ALL
SELECT 'band_id', band_id FROM latest_meeting
UNION ALL
SELECT 'user_id', user_id FROM probe_user;

.print '\n[Q1] membership(user,band,is_approved)'
EXPLAIN QUERY PLAN
WITH latest_meeting AS (
  SELECT id AS meeting_id, band_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
),
probe_user AS (
  SELECT m.user_id
  FROM pracapp_membership m
  JOIN latest_meeting lm ON lm.band_id = m.band_id
  WHERE m.is_approved = 1
  ORDER BY m.rowid ASC
  LIMIT 1
)
SELECT 1
FROM pracapp_membership m
JOIN latest_meeting lm ON lm.band_id = m.band_id
JOIN probe_user pu ON pu.user_id = m.user_id
WHERE m.is_approved = 1
LIMIT 1;

.print '\n[Q2] membership(band,is_approved,role IN)'
EXPLAIN QUERY PLAN
WITH latest_meeting AS (
  SELECT band_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
)
SELECT 1
FROM pracapp_membership m
JOIN latest_meeting lm ON lm.band_id = m.band_id
WHERE m.is_approved = 1
  AND m.role IN ('LEADER','MANAGER')
LIMIT 1;

.print '\n[Q3] song list by meeting'
EXPLAIN QUERY PLAN
WITH latest_meeting AS (
  SELECT id AS meeting_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
)
SELECT s.id, s.title
FROM pracapp_song s
JOIN latest_meeting lm ON lm.meeting_id = s.meeting_id;

.print '\n[Q4] session prefetch style (song_id + applicant subqueries)'
EXPLAIN QUERY PLAN
WITH latest_meeting AS (
  SELECT id AS meeting_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
),
probe_user AS (
  SELECT m.user_id
  FROM pracapp_membership m
  JOIN pracapp_meeting mt ON mt.band_id = m.band_id
  JOIN latest_meeting lm ON lm.meeting_id = mt.id
  WHERE m.is_approved = 1
  ORDER BY m.rowid ASC
  LIMIT 1
)
SELECT ss.id,
       ss.song_id,
       ss.name,
       (SELECT COUNT(DISTINCT a.user_id)
          FROM pracapp_session_applicant a
         WHERE a.session_id = ss.id) AS applicant_count,
       EXISTS(
         SELECT 1
         FROM pracapp_session_applicant x
         JOIN probe_user pu ON pu.user_id = x.user_id
         WHERE x.session_id = ss.id
       ) AS my_applied
FROM pracapp_session ss
WHERE ss.song_id IN (
  SELECT s.id
  FROM pracapp_song s
  JOIN latest_meeting lm ON lm.meeting_id = s.meeting_id
);

.print '\n[Q5] rooms by band + temporary flag + order name'
EXPLAIN QUERY PLAN
WITH latest_meeting AS (
  SELECT band_id
  FROM pracapp_meeting
  ORDER BY rowid DESC
  LIMIT 1
)
SELECT r.id, r.name, r.capacity
FROM pracapp_practiceroom r
JOIN latest_meeting lm ON lm.band_id = r.band_id
WHERE r.is_temporary = 0
ORDER BY r.name;
