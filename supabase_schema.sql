-- Create raw_roster_data table
CREATE TABLE raw_roster_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    name TEXT NOT NULL,
    emp_id TEXT NOT NULL,
    duty_code_raw TEXT NOT NULL,
    shift_start TIME,
    shift_end TIME,
    crew_type TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create processed_roster table
CREATE TABLE processed_roster (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    emp_id TEXT NOT NULL,
    duty_category TEXT NOT NULL,
    duty_code TEXT NOT NULL,
    shift_type TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create daily_summary table
CREATE TABLE daily_summary (
    date DATE PRIMARY KEY,
    on_duty_count INTEGER DEFAULT 0,
    general_shift_count INTEGER DEFAULT 0,
    leave_count INTEGER DEFAULT 0,
    absent_count INTEGER DEFAULT 0,
    weekly_off_count INTEGER DEFAULT 0,
    standby_count INTEGER DEFAULT 0,
    depot_count INTEGER DEFAULT 0,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Note: RLS (Row Level Security) and policies can be configured from the Supabase UI 
-- according to your auth setup.
