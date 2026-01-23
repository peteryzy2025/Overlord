-- SQL Script to update database for App renaming (Uppercase -> Lowercase)
-- Run this in your PostgreSQL database (e.g., using pgAdmin or psql)

-- 1. Rename tables for apps that use default naming (Track, Zother)
-- Most other apps (Amazon, General, Task, etc.) use explicit db_table in Meta, so they don't need table renaming.

-- Track App
ALTER TABLE IF EXISTS "Track_factory" RENAME TO "track_factory";
ALTER TABLE IF EXISTS "Track_courier" RENAME TO "track_courier";
ALTER TABLE IF EXISTS "Track_tracking" RENAME TO "track_tracking";
ALTER TABLE IF EXISTS "Track_trackingdetail" RENAME TO "track_trackingdetail";

-- Zother App
ALTER TABLE IF EXISTS "Zother_bargainingorder" RENAME TO "zother_bargainingorder";

-- 2. Update django_content_type
-- This ensures generic relations and permissions work with the new app labels.
UPDATE django_content_type SET app_label = 'amazon' WHERE app_label = 'Amazon';
UPDATE django_content_type SET app_label = 'general' WHERE app_label = 'General';
UPDATE django_content_type SET app_label = 'task' WHERE app_label = 'Task';
UPDATE django_content_type SET app_label = 'temu' WHERE app_label = 'Temu';
UPDATE django_content_type SET app_label = 'theme' WHERE app_label = 'Theme';
UPDATE django_content_type SET app_label = 'track' WHERE app_label = 'Track';
UPDATE django_content_type SET app_label = 'yuser' WHERE app_label = 'Yuser';
UPDATE django_content_type SET app_label = 'zother' WHERE app_label = 'Zother';

-- 3. Update django_migrations
-- This ensures Django recognizes existing migrations as applied for the new app names.
UPDATE django_migrations SET app = 'amazon' WHERE app = 'Amazon';
UPDATE django_migrations SET app = 'general' WHERE app = 'General';
UPDATE django_migrations SET app = 'task' WHERE app = 'Task';
UPDATE django_migrations SET app = 'temu' WHERE app = 'Temu';
UPDATE django_migrations SET app = 'theme' WHERE app = 'Theme';
UPDATE django_migrations SET app = 'track' WHERE app = 'Track';
UPDATE django_migrations SET app = 'yuser' WHERE app = 'Yuser';
UPDATE django_migrations SET app = 'zother' WHERE app = 'Zother';
