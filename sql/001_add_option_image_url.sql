-- Đáp án câu 6-15 và 26-30 là TRANH, bảng answer_options cần thêm cột ảnh.
ALTER TABLE answer_options
    ADD COLUMN IF NOT EXISTS option_image_url TEXT;

-- Kiểm tra ràng buộc question_type (nếu có CHECK) để chắc chắn chấp nhận
-- 'true_false' và 'multiple_choice':
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'questions'::regclass AND contype = 'c';
