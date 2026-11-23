@echo off
REM Replays every campaign of the paper on Windows (Command Prompt, not PowerShell).
REM Usage:
REM   replay_all.bat                          uses the exports in data\
REM   replay_all.bat flask.json nyc311.json   uses other copies of the two exports
REM Results go to replay\ ; the CSV files shipped with the artifact are not modified.

setlocal
cd /d "%~dp0"
set F=%~f1
set N=%~f2
if "%F%"=="" set F=%CD%\data\github_issues.json
if "%N%"=="" set N=%CD%\data\nyc311_200.json
set OUT=replay
if not exist %OUT% mkdir %OUT%
python --version || goto :fail
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"

echo.
echo === Section 6: factorial design N x R (a few minutes) ===
set PYTHONPATH=benchmark_read_write
python benchmark_scale\scale.py --environment %OUT%\scale_environment.txt > %OUT%\scale_measurements.csv || goto :fail
python benchmark_scale\analyze_scale.py %OUT%\scale_measurements.csv > %OUT%\scale_summary.csv || goto :fail
python -c "import matplotlib" 2>nul && python benchmark_scale\analyze_scale.py %OUT%\scale_measurements.csv %OUT%\scale_tradeoff.pdf > nul

echo.
echo === Section 7: object keys and constructor ablation (longest, 15-30 min) ===
set PYTHONPATH=benchmark_read_write;benchmark_objects_v10
python benchmark_objects_v10\objects.py --environment %OUT%\objects_environment.txt > %OUT%\objects_measurements.csv || goto :fail
python benchmark_objects_v10\analyze_objects.py %OUT%\objects_measurements.csv --phases %OUT%\objects_phases.csv > %OUT%\objects_summary.csv || goto :fail

echo.
echo === Section 8: space ===
set PYTHONPATH=benchmark_read_write;benchmark_space
python benchmark_space\ordkeys.py || goto :fail
python benchmark_space\space.py > %OUT%\space_sizes.csv || goto :fail
python benchmark_space\summarize_space.py %OUT%\space_sizes.csv > %OUT%\space_summary.csv || goto :fail

echo.
echo === Section 9: positional access and sibling-index size ===
python benchmark_space\positional.py > %OUT%\positional.csv || goto :fail
set PYTHONPATH=
python benchmark_space\sibling_index_size.py > %OUT%\sibling_index_size.txt || goto :fail

if not exist "%F%" goto :noexports
if not exist "%N%" goto :noexports

echo.
echo === Section 5.1: Dewey-DDE crossover, generic constructor ===
if not exist %OUT%\global mkdir %OUT%\global
python benchmark_global\run.py "%F%" "%N%" > %OUT%\global\measurements.csv || goto :fail
pushd %OUT%\global
python ..\..\benchmark_global\analyze.py > summary.csv || (popd & goto :fail)
popd

echo.
echo === Section 5.2: local maintenance by position ===
python benchmark_local\local.py "%F%" "%N%" > %OUT%\local_measurements.csv || goto :fail
python benchmark_local\summarize.py %OUT%\local_measurements.csv > %OUT%\local_summary.csv || goto :fail

echo.
echo === Section 9: mixed edits and reads ===
python benchmark_read_write\mixed.py "%F%" "%N%" > %OUT%\mixed_measurements.csv || goto :fail
python benchmark_read_write\summarize_mixed.py %OUT%\mixed_measurements.csv > %OUT%\mixed_summary.csv || goto :fail
goto :done

:noexports
echo.
echo Exports not found: Sections 5.1, 5.2, and the reads of Section 9 were skipped.

:done
echo.
echo Done. Results in %CD%\%OUT%
exit /b 0

:fail
echo.
echo FAILED at the step above. See the Python error message.
exit /b 1
