-- Add unique constraint to raw_roster_data to enable upsert diffing
ALTER TABLE raw_roster_data
ADD CONSTRAINT raw_roster_date_emp_id_key UNIQUE (date, emp_id);

-- Add unique constraint to processed_roster to enable upsert diffing
ALTER TABLE processed_roster
ADD CONSTRAINT processed_roster_date_emp_id_key UNIQUE (date, emp_id);
