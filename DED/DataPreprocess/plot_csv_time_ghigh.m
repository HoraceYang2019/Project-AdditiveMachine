function plot_csv_time_ghigh(csvPath)
%PLOT_CSV_TIME_GHIGH Plot Time vs G-High from a CSV file.
% Usage:
%   plot_csv_time_ghigh
%   plot_csv_time_ghigh("Final/csv/your_file.csv")

    if nargin < 1 || strlength(string(csvPath)) == 0
        [fileName, folderPath] = uigetfile({'*.csv', 'CSV files (*.csv)'}, 'Select a CSV file');
        if isequal(fileName, 0)
            disp('No file selected.');
            return;
        end
        csvPath = fullfile(folderPath, fileName);
    end

    csvPath = char(string(csvPath));
    if ~isfile(csvPath)
        error('CSV file not found: %s', csvPath);
    end

    opts = detectImportOptions(csvPath, 'VariableNamingRule', 'preserve');
    dataTable = readtable(csvPath, opts);

    if isempty(dataTable) || width(dataTable) == 0
        error('The CSV file does not contain readable columns.');
    end

    timeColumnName = findColumnName(dataTable.Properties.VariableNames, ...
        {'Time', 'Timestamp', 'DateTime', 'Datetime', 'RecordedTime', 'TimeStamp'}, ...
        {'time', 'timestamp', 'datetime', 'recordedtime'});
    gHighColumnName = findColumnName(dataTable.Properties.VariableNames, ...
        {'G_High', 'G-High', 'G High', 'GHigh', 'ghigh'}, ...
        {'ghigh'});

    if isempty(timeColumnName)
        error('Could not find a Time column.');
    end
    if isempty(gHighColumnName)
        error('Could not find a G-High column.');
    end

    rawTime = dataTable.(timeColumnName);
    rawGHigh = dataTable.(gHighColumnName);

    [timeValues, timeLabel, isDateTimeAxis] = parseTimeColumn(rawTime, timeColumnName);
    gHighValues = parseNumericColumn(rawGHigh);

    validMask = ~isnan(gHighValues);
    if isDateTimeAxis
        validMask = validMask & ~isnat(timeValues);
    else
        validMask = validMask & ~isnan(timeValues);
    end

    timeValues = timeValues(validMask);
    gHighValues = gHighValues(validMask);

    if isempty(gHighValues)
        error('No valid Time and G-High samples were found after cleaning.');
    end

    figure('Color', 'w', 'Name', 'Time vs G-High');
    plot(timeValues, gHighValues, 'LineWidth', 1.5, 'Color', [0.85, 0.33, 0.10]);
    grid on;
    box on;
    xlabel(timeLabel, 'Interpreter', 'none');
    ylabel('G-High', 'Interpreter', 'none');
    title(sprintf('Time vs G-High\n%s', csvPath), 'Interpreter', 'none');

    if isDateTimeAxis
        ax = gca;
        ax.XAxis.TickLabelFormat = 'yyyy-MM-dd HH:mm:ss.SSS';
    end

    fprintf('Loaded file: %s\n', csvPath);
    fprintf('Time column: %s\n', timeColumnName);
    fprintf('G-High column: %s\n', gHighColumnName);
    fprintf('Plotted samples: %d\n', numel(gHighValues));
end


function columnName = findColumnName(variableNames, candidateNames, fallbackTokens)
    columnName = '';

    normalizedNames = cellfun(@normalizeName, variableNames, 'UniformOutput', false);

    for index = 1:numel(candidateNames)
        candidate = normalizeName(candidateNames{index});
        matchIndex = find(strcmp(normalizedNames, candidate), 1);
        if ~isempty(matchIndex)
            columnName = variableNames{matchIndex};
            return;
        end
    end

    for index = 1:numel(variableNames)
        currentName = normalizedNames{index};
        if any(strcmp(currentName, fallbackTokens))
            columnName = variableNames{index};
            return;
        end
    end
end


function normalized = normalizeName(textValue)
    normalized = lower(regexprep(char(string(textValue)), '[^a-zA-Z0-9]', ''));
end


function [timeValues, timeLabel, isDateTimeAxis] = parseTimeColumn(rawTime, timeColumnName)
    isDateTimeAxis = false;
    timeLabel = char(string(timeColumnName));

    if isdatetime(rawTime)
        timeValues = rawTime;
        isDateTimeAxis = true;
        return;
    end

    if isnumeric(rawTime)
        timeValues = double(rawTime);
        return;
    end

    if isduration(rawTime)
        timeValues = seconds(rawTime);
        timeLabel = sprintf('%s (s)', timeLabel);
        return;
    end

    textValues = string(rawTime);
    parsedDateTime = tryParseDateTime(textValues);
    if ~isempty(parsedDateTime)
        timeValues = parsedDateTime;
        isDateTimeAxis = true;
        return;
    end

    numericValues = str2double(textValues);
    if any(~isnan(numericValues))
        timeValues = numericValues;
        return;
    end

    error('The Time column could not be parsed.');
end


function parsedDateTime = tryParseDateTime(textValues)
    parsedDateTime = [];

    textValues = strip(textValues);
    textValues = regexprep(textValues, '(\d{2}:\d{2}:\d{2}):(\d{1,6})$', '$1.$2');
    textValues(textValues == "") = missing;

    parseFormats = {
        'yyyy-MM-dd HH:mm:ss.SSS'
        'yyyy-MM-dd HH:mm:ss'
        'yyyy/MM/dd HH:mm:ss.SSS'
        'yyyy/MM/dd HH:mm:ss'
        'MM/dd/yyyy HH:mm:ss.SSS'
        'MM/dd/yyyy HH:mm:ss'
        'dd-MMM-yyyy HH:mm:ss.SSS'
        'dd-MMM-yyyy HH:mm:ss'
        };

    for index = 1:numel(parseFormats)
        try
            candidate = datetime(textValues, 'InputFormat', parseFormats{index});
            if any(~isnat(candidate))
                parsedDateTime = candidate;
                return;
            end
        catch
        end
    end

    try
        candidate = datetime(textValues);
        if any(~isnat(candidate))
            parsedDateTime = candidate;
        end
    catch
    end
end


function numericValues = parseNumericColumn(rawValues)
    if isnumeric(rawValues)
        numericValues = double(rawValues);
        return;
    end

    if islogical(rawValues)
        numericValues = double(rawValues);
        return;
    end

    textValues = string(rawValues);
    numericValues = str2double(textValues);
end
