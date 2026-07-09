# sudoplz Project Guidelines

## Project Overview
sudoplz gives AI coding agents (Claude Code, Cursor, etc.) the ability to run `sudo` commands via a real GUI password prompt. No password is ever stored — sudo validates it the normal way. The project ships two entry points:
- `askpass` - Invoked by `sudo -A` via `SUDO_ASKPASS`; performs security checks, prompts for the sudo password (GUI, or `/dev/tty` when headless), and prints whatever was typed for sudo to validate
- `sudoplz` - Management CLI (test/audit/config)

## Development Guidelines

1. **Tool Usage**:
   - Use `bash` commands directly for basic operations
   - For complex searches, use the `Task` tool
   - When making multiple bash calls, use `Batch` for parallel execution

2. **Code Style**:
   - Follow existing conventions in the askpass scripts
   - Keep scripts minimal and focused on single responsibilities
   - No unnecessary comments unless explicitly requested

3. **Testing**:
   - Test both `askpass` and `sudoplz` components
   - Ensure secure password handling

4. **Security**:
   - Never log or expose passwords in plain text
   - Never write the password to disk or hold it longer than needed to hand it to sudo
   - Follow secure coding practices for password handling

5. **Commits**:
   - Only commit when explicitly requested
   - Follow existing commit style from git history