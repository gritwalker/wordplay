-- Supabase 테이블 생성 스크립트
-- diaries 테이블 생성
CREATE TABLE IF NOT EXISTS public.diaries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- calendar_events 테이블 생성  
CREATE TABLE IF NOT EXISTS public.calendar_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT,
    date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- memos 테이블 생성
CREATE TABLE IF NOT EXISTS public.memos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    title TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- RLS (Row Level Security) 정책 설정
ALTER TABLE public.diaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memos ENABLE ROW LEVEL SECURITY;

-- diaries 테이블 RLS 정책
CREATE POLICY "Users can view their own diaries" ON public.diaries
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own diaries" ON public.diaries
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own diaries" ON public.diaries
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own diaries" ON public.diaries
    FOR DELETE USING (auth.uid() = user_id);

-- calendar_events 테이블 RLS 정책
CREATE POLICY "Users can view their own calendar events" ON public.calendar_events
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own calendar events" ON public.calendar_events
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own calendar events" ON public.calendar_events
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own calendar events" ON public.calendar_events
    FOR DELETE USING (auth.uid() = user_id);

-- memos 테이블 RLS 정책
CREATE POLICY "Users can view their own memos" ON public.memos
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own memos" ON public.memos
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own memos" ON public.memos
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own memos" ON public.memos
    FOR DELETE USING (auth.uid() = user_id);