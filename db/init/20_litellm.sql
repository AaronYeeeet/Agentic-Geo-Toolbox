-- Separate database for LiteLLM (keys, budgets, spend logs), so its tables
-- don't mix with our geodata in the main database.
-- Runs only when the db volume is created for the first time.
--
-- litellm schreib die selbst, müssen uns vorerst nicht drum kümmern
CREATE DATABASE litellm;
