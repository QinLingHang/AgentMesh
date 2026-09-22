param(
    [string]$Python = "python.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
$KafkaName = "agentmesh-p21-task-kafka-$Suffix"
$MySQLName = "agentmesh-p21-task-mysql-$Suffix"
$RedisName = "agentmesh-p21-task-redis-$Suffix"
$Database = "agentmesh_p21_task_$Suffix"
$Topic = "p21.task.$Suffix.events"
$DLQTopic = "p21.task.$Suffix.dlq"
$Group = "p21-task-$Suffix-group"
$KafkaPort = 39093
$MySQLPort = 43311
$RedisPort = 46383
$GoPort = 18087
$RuntimePort = 19573
$InternalToken = "qa-$([guid]::NewGuid().ToString('N'))"
$JwtSecret = "qa-jwt-$([guid]::NewGuid().ToString('N'))"
$GovernanceKey = "qa-gov-$([guid]::NewGuid().ToString('N'))"
$VerificationPepper = "qa-verify-$([guid]::NewGuid().ToString('N'))"
$MySQLPassword = "qa$([guid]::NewGuid().ToString('N'))"
$Email = "p21-task-$Suffix@example.test"
$Password = "P21-QA-$([guid]::NewGuid().ToString('N'))!"
$TempRoot = Join-Path $env:TEMP "agentmesh-p21-task-$Suffix"
$Outbox = Join-Path $TempRoot "runtime-result-outbox.sqlite3"
$GoLog = Join-Path $TempRoot "go.log"
$GoErr = Join-Path $TempRoot "go.err.log"
$RuntimeLog = Join-Path $TempRoot "runtime.log"
$RuntimeErr = Join-Path $TempRoot "runtime.err.log"
$GoCache = Join-Path $TempRoot "go-cache"
$GoBinary = Join-Path $TempRoot "p21-qa-server.exe"
$TempSchema = Join-Path $TempRoot "schema.sql"
$OutboxInspector = Join-Path $TempRoot "inspect_outbox.py"
$EvidenceDir = Join-Path $Root "docs\implementation\evidence"
$EvidencePath = Join-Path $EvidenceDir "P21_FINAL_TASK_OUTAGE_$Stamp-$Suffix.json"
$GoProcess = $null
$RuntimeProcess = $null
$CreatedContainers = [System.Collections.Generic.List[string]]::new()
$Timeline = [System.Collections.Generic.List[object]]::new()
$oldEnv = @{}

function Add-Time([string]$Event, [hashtable]$Data = @{}) {
    $entry = [ordered]@{ at = (Get-Date).ToUniversalTime().ToString("o"); event = $Event }
    foreach ($key in $Data.Keys) { $entry[$key] = $Data[$key] }
    $Timeline.Add([pscustomobject]$entry)
}

function Wait-Http([string]$Url, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try { return Invoke-RestMethod -Uri $Url -TimeoutSec 2 }
        catch { Start-Sleep -Milliseconds 500 }
    } while ((Get-Date) -lt $deadline)
    throw "health timeout: $Url"
}

function Invoke-Api([string]$Method, [string]$Path, $Body = $null, [string]$Token = "") {
    $headers = @{}
    if ($Token) { $headers.Authorization = "Bearer $Token" }
    $args = @{ Method = $Method; Uri = "http://127.0.0.1:$GoPort$Path"; Headers = $headers; TimeoutSec = 20 }
    if ($null -ne $Body) {
        $args.ContentType = "application/json"
        $args.Body = ($Body | ConvertTo-Json -Depth 12 -Compress)
    }
    Invoke-RestMethod @args
}

function Invoke-MySQL([string]$Query) {
    $result = docker exec -e "MYSQL_PWD=$MySQLPassword" $MySQLName mysql -uroot -N -B $Database -e $Query
    if ($LASTEXITCODE -ne 0) { throw "QA MySQL query failed" }
    ($result -join "`n").Trim()
}

function Wait-MySQLValue([string]$Query, [scriptblock]$Accept, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $value = Invoke-MySQL $Query
        if (& $Accept $value) { return $value }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    throw "database state timeout"
}

function Get-OutboxState {
    if (-not (Test-Path -LiteralPath $Outbox)) { return [pscustomobject]@{ rows = 0; eventId = $null; attemptCount = 0 } }
    $code = @'
import json, sqlite3, sys
with sqlite3.connect(sys.argv[1]) as c:
    try:
        row = c.execute("select event_id, attempt_count, count(*) from kafka_result_outbox").fetchone()
    except sqlite3.OperationalError:
        row = (None, 0, 0)
print(json.dumps({"eventId": row[0], "attemptCount": row[1], "rows": row[2]}))
'@
    Set-Content -LiteralPath $OutboxInspector -Value $code -Encoding UTF8
    $raw = & $Python $OutboxInspector $Outbox
    if ($LASTEXITCODE -ne 0) { throw "outbox inspection failed" }
    $raw | ConvertFrom-Json
}

function Stop-LocalProcess($Process) {
    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }
}

New-Item -ItemType Directory -Path $TempRoot, $GoCache, $EvidenceDir -Force | Out-Null
$evidence = [ordered]@{
    schemaVersion = 1
    generatedAt = (Get-Date).ToUniversalTime().ToString("o")
    branch = (git -C $Root branch --show-current).Trim()
    head = (git -C $Root rev-parse HEAD).Trim()
    qa = [ordered]@{ suffix=$Suffix; kafkaPort=$KafkaPort; mysqlPort=$MySQLPort; redisPort=$RedisPort; goPort=$GoPort; runtimePort=$RuntimePort; topic=$Topic; dlqTopic=$DLQTopic; consumerGroup=$Group; database=$Database }
    timeline = $Timeline
    result = "RUNNING"
}

try {
    foreach ($port in @($KafkaPort,$MySQLPort,$RedisPort,$GoPort,$RuntimePort)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "QA port already in use: $port" }
    }

    docker run -d --name $MySQLName -e MYSQL_ROOT_PASSWORD=$MySQLPassword -e MYSQL_DATABASE=$Database -p "${MySQLPort}:3306" mysql:8.4 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "start QA MySQL failed" }; $CreatedContainers.Add($MySQLName)
    docker run -d --name $RedisName -p "${RedisPort}:6379" redis:7.4-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "start QA Redis failed" }; $CreatedContainers.Add($RedisName)
    docker run -d --name $KafkaName -p "${KafkaPort}:${KafkaPort}" `
      -e KAFKA_NODE_ID=1 -e KAFKA_PROCESS_ROLES=broker,controller `
      -e "KAFKA_LISTENERS=INTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093,EXTERNAL://0.0.0.0:$KafkaPort" `
      -e "KAFKA_ADVERTISED_LISTENERS=INTERNAL://127.0.0.1:9092,EXTERNAL://127.0.0.1:$KafkaPort" `
      -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,INTERNAL:PLAINTEXT,EXTERNAL:PLAINTEXT `
      -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER -e KAFKA_INTER_BROKER_LISTENER_NAME=INTERNAL `
      -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@127.0.0.1:9093 `
      -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 `
      -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 -e KAFKA_NUM_PARTITIONS=1 -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true `
      apache/kafka:3.9.1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "start QA Kafka failed" }; $CreatedContainers.Add($KafkaName)
    Add-Time "qa_containers_started"

    $mysqlReady=$false
    $savedErrorPreference=$ErrorActionPreference; $ErrorActionPreference="SilentlyContinue"
    try { for($i=0;$i -lt 100;$i++){ docker exec -e "MYSQL_PWD=$MySQLPassword" $MySQLName mysql -uroot -N -B -e "SELECT 1" 2>&1 | Out-Null; if($LASTEXITCODE -eq 0){$mysqlReady=$true;break}; Start-Sleep -Milliseconds 500 } }
    finally { $ErrorActionPreference=$savedErrorPreference }
    if(-not $mysqlReady){throw "QA MySQL readiness failed"}
    $schema = (Get-Content -LiteralPath (Join-Path $Root "infra\mysql\init\001_schema.sql") -Raw -Encoding UTF8).Replace("agentmesh_mvp", $Database)
    Set-Content -LiteralPath $TempSchema -Value $schema -Encoding UTF8
    docker cp $TempSchema "${MySQLName}:/tmp/p21-schema.sql" | Out-Null
    if($LASTEXITCODE -ne 0){throw "QA schema copy failed"}
    docker exec -e "MYSQL_PWD=$MySQLPassword" $MySQLName mysql -uroot -e "source /tmp/p21-schema.sql"
    if($LASTEXITCODE -ne 0){throw "QA schema init failed"}
    $kafkaReady=$false
    $savedErrorPreference=$ErrorActionPreference; $ErrorActionPreference="SilentlyContinue"
    try { for($i=0;$i -lt 100;$i++){ docker exec $KafkaName /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --list 2>&1 | Out-Null; if($LASTEXITCODE -eq 0){$kafkaReady=$true;break}; Start-Sleep -Milliseconds 500 } }
    finally { $ErrorActionPreference=$savedErrorPreference }
    if(-not $kafkaReady){throw "QA Kafka readiness failed"}
    foreach($name in @($Topic,$DLQTopic)){ docker exec $KafkaName /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic $name --partitions 1 --replication-factor 1 | Out-Null; if($LASTEXITCODE -ne 0){throw "topic create failed"} }
    Add-Time "qa_infrastructure_ready"

    $goEnv = [ordered]@{
        BUSINESS_PORT="$GoPort"; MYSQL_HOST="127.0.0.1"; MYSQL_PORT="$MySQLPort"; MYSQL_DATABASE=$Database; MYSQL_USER="root"; MYSQL_PASSWORD=$MySQLPassword
        REDIS_ADDR="127.0.0.1:$RedisPort"; REDIS_DB="0"; JWT_SECRET=$JwtSecret; GOVERNANCE_MASTER_KEY=$GovernanceKey; VERIFICATION_PEPPER=$VerificationPepper
        EMAIL_PROVIDER="console"; RUNTIME_BASE_URL="http://127.0.0.1:$RuntimePort"; RUNTIME_INTERNAL_TOKEN=$InternalToken; CONTROL_PLANE_INTERNAL_BASE_URL="http://127.0.0.1:$GoPort"
        DURABLE_RUNTIME_ENABLED="true"; DURABLE_RUNTIME_POLL_MS="100"; DURABLE_RUNTIME_WORKER_STALE_SECONDS="20"; DURABLE_RUNTIME_JOB_DEADLINE_SECONDS="120"
        KAFKA_ENABLED="true"; KAFKA_BROKERS="127.0.0.1:$KafkaPort"; KAFKA_RUNTIME_EVENTS_TOPIC=$Topic; KAFKA_RUNTIME_DLQ_TOPIC=$DLQTopic; KAFKA_RUNTIME_CONSUMER_GROUP=$Group; KAFKA_CLIENT_ID="p21-task-go-$Suffix"; GOCACHE=$GoCache
    }
    foreach($item in $goEnv.GetEnumerator()){ $oldEnv[$item.Key]=[Environment]::GetEnvironmentVariable($item.Key,"Process"); [Environment]::SetEnvironmentVariable($item.Key,$item.Value,"Process") }
    & go.exe -C (Join-Path $Root "backend-go") build -o $GoBinary ./cmd/server
    if($LASTEXITCODE -ne 0){throw "QA Go build failed"}
    $GoProcess=Start-Process -FilePath $GoBinary -WorkingDirectory (Join-Path $Root "backend-go") -WindowStyle Hidden -RedirectStandardOutput $GoLog -RedirectStandardError $GoErr -PassThru
    Wait-Http "http://127.0.0.1:$GoPort/readyz" 120 | Out-Null

    $runtimeEnv = [ordered]@{
        INTERNAL_TOKEN=$InternalToken; RUNTIME_WORKER_ENABLED="true"; RUNTIME_WORKER_ID="p21-task-worker-$Suffix"; RUNTIME_WORKER_ENDPOINT="http://127.0.0.1:$RuntimePort"; RUNTIME_WORKER_CAPACITY="1"
        CONTROL_PLANE_INTERNAL_BASE_URL="http://127.0.0.1:$GoPort"; RUNTIME_WORKER_HEARTBEAT_SECONDS="1"; RUNTIME_RESULT_TRANSPORT="kafka"; KAFKA_BROKERS="127.0.0.1:$KafkaPort"; KAFKA_RUNTIME_RESULT_TOPIC=$Topic; KAFKA_CLIENT_ID="p21-task-python-$Suffix"; KAFKA_OUTBOX_PATH=$Outbox; KAFKA_PUBLISH_TIMEOUT_SECONDS="1"
    }
    foreach($item in $runtimeEnv.GetEnumerator()){ if(-not $oldEnv.ContainsKey($item.Key)){$oldEnv[$item.Key]=[Environment]::GetEnvironmentVariable($item.Key,"Process")}; [Environment]::SetEnvironmentVariable($item.Key,$item.Value,"Process") }
    $RuntimeProcess=Start-Process -FilePath $Python -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$RuntimePort") -WorkingDirectory (Join-Path $Root "runtime-python") -WindowStyle Hidden -RedirectStandardOutput $RuntimeLog -RedirectStandardError $RuntimeErr -PassThru
    $runtimeHealth=Wait-Http "http://127.0.0.1:$RuntimePort/health" 90
    Add-Time "local_go_python_ready" @{ workerId="p21-task-worker-$Suffix" }

    $null=Invoke-Api "POST" "/api/auth/email/code" @{email=$Email;scene="register"}
    $code=$null; $deadline=(Get-Date).AddSeconds(20)
    do { $match=Select-String -Path $GoLog,$GoErr -Pattern ([regex]::Escape("to=$Email")+" scene=register code=(\d{6})") -ErrorAction SilentlyContinue | Select-Object -Last 1; if($match){$code=$match.Matches[0].Groups[1].Value;break};Start-Sleep -Milliseconds 200 } while((Get-Date)-lt $deadline)
    if(-not $code){throw "verification code not observed"}
    $registration=Invoke-Api "POST" "/api/auth/register/verify" @{email=$Email;code=$code;password=$Password;displayName="P21 Task QA"}
    $Token=$registration.data.accessToken
    if(-not $Token){throw "registration token missing"}
    $null=Invoke-Api "POST" "/api/agents/seed-demo" $null $Token
    $null=Invoke-Api "POST" "/api/me/model-services" @{name="P21 QA Mock";provider="mock";baseUrl="https://example.invalid/v1";modelName="agentmesh-qa-mock";visionModelName="";apiKey="qa-only-not-used";enabled=$true;autoRoute=$true;isDefault=$true} $Token
    $conversation=Invoke-Api "POST" "/api/conversations" @{title="P21 final outage QA"} $Token
    $ConversationId=[int64]$conversation.data.id
    $workerOnline=$false; $deadline=(Get-Date).AddSeconds(30)
    do { $topology=Invoke-Api "GET" "/api/runtime/topology" $null $Token; $workerOnline=[bool]($topology.data.workers | Where-Object {$_.workerId -eq "p21-task-worker-$Suffix" -and $_.status -eq "ACTIVE"}); if($workerOnline){break}; Start-Sleep -Milliseconds 300 } while((Get-Date)-lt $deadline)
    if(-not $workerOnline){throw "worker not ACTIVE"}
    Add-Time "authenticated_qa_ready" @{ conversationId=$ConversationId; workerOnline=$true }

    docker stop $KafkaName | Out-Null
    if($LASTEXITCODE -ne 0){throw "QA Kafka stop failed"}
    Add-Time "qa_broker_stopped"

    $clientRequestId="p21-task-$Suffix"
    $submit=Invoke-Api "POST" "/api/tasks/run-durable" @{clientRequestId=$clientRequestId;conversationId=$ConversationId;task="P21 deterministic completion";scheduler="adaptive";planner="multi_objective";executionMode="auto";synthesisMode="auto";constraints=@{maxLatencyMs=8000;maxCost=0.15;minQuality=0.8;retryOnWorkerLoss=$false}} $Token
    $TaskId=[int64]$submit.data.task.id
    if($TaskId -le 0){throw "durable task id missing"}
    Add-Time "durable_task_submitted_while_broker_down" @{ taskId=$TaskId }

    $null=Wait-MySQLValue "SELECT status FROM runtime_jobs WHERE task_id=$TaskId" { param($v) $v -eq "RESULT_PENDING" } 90
    $jobRow=Invoke-MySQL "SELECT id,execution_id,fence_epoch,COALESCE(worker_id,''),status FROM runtime_jobs WHERE task_id=$TaskId"
    $parts=$jobRow -split "`t"; $JobId=[int64]$parts[0];$ExecutionId=$parts[1];$Fence=[int64]$parts[2];$WorkerId=$parts[3]
    if($parts[4] -ne "RESULT_PENDING" -or -not $ExecutionId -or -not $WorkerId){throw "runtime job identity incomplete during outage"}
    $TaskDuring=Invoke-MySQL "SELECT status FROM tasks WHERE id=$TaskId"
    $outboxState=$null;$deadline=(Get-Date).AddSeconds(30)
    do{$outboxState=Get-OutboxState;if($outboxState.rows -eq 1 -and $outboxState.attemptCount -ge 1){break};Start-Sleep -Milliseconds 300}while((Get-Date)-lt $deadline)
    if($outboxState.rows -ne 1){throw "outbox row missing during outage"}
    $runtimeDuring=Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/health" -TimeoutSec 5
    $unclosedDuring=@(Select-String -LiteralPath $RuntimeErr -Pattern "Unclosed AIOKafkaProducer" -ErrorAction SilentlyContinue).Count
    if($unclosedDuring -ne 0){throw "Unclosed AIOKafkaProducer observed during outage"}
    Add-Time "outage_state_verified" @{ taskId=$TaskId;jobId=$JobId;executionId=$ExecutionId;fenceEpoch=$Fence;workerId=$WorkerId;taskStatus=$TaskDuring;jobStatus="RESULT_PENDING";eventId=$outboxState.eventId;outboxRows=$outboxState.rows;attemptCount=$outboxState.attemptCount;produceFailed=$runtimeDuring.resultTransport.produceFailed;unclosedWarnings=$unclosedDuring }

    docker start $KafkaName | Out-Null
    $kafkaReady=$false
    $savedErrorPreference=$ErrorActionPreference; $ErrorActionPreference="SilentlyContinue"
    try { for($i=0;$i -lt 100;$i++){ docker exec $KafkaName /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --list 2>&1 | Out-Null; if($LASTEXITCODE -eq 0){$kafkaReady=$true;break};Start-Sleep -Milliseconds 500 } }
    finally { $ErrorActionPreference=$savedErrorPreference }
    if(-not $kafkaReady){throw "QA Kafka restart readiness failed"}
    Add-Time "qa_broker_restored"

    $null=Wait-MySQLValue "SELECT CONCAT(t.status,'|',j.status) FROM tasks t JOIN runtime_jobs j ON j.task_id=t.id WHERE t.id=$TaskId" { param($v) $v -eq "COMPLETED|COMPLETED" } 120
    $finalOutbox=$null;$deadline=(Get-Date).AddSeconds(30);do{$finalOutbox=Get-OutboxState;if($finalOutbox.rows -eq 0){break};Start-Sleep -Milliseconds 300}while((Get-Date)-lt $deadline)
    if($finalOutbox.rows -ne 0){throw "outbox did not drain"}
    $ledger=Invoke-MySQL "SELECT event_id,topic_name,partition_id,offset_value FROM processed_runtime_events WHERE execution_id='$ExecutionId'"
    $ledgerParts=$ledger -split "`t"; if($ledgerParts.Count -ne 4){throw "processed event ledger missing"}
    $EventId=$ledgerParts[0];$Partition=[int]$ledgerParts[2];$Offset=[int64]$ledgerParts[3]
    if($EventId -ne $outboxState.eventId){throw "event id changed across recovery"}
    $assistantCount=[int](Invoke-MySQL "SELECT COUNT(*) FROM messages WHERE conversation_id=$ConversationId AND role='assistant'")
    $taskCount=[int](Invoke-MySQL "SELECT COUNT(*) FROM tasks WHERE id=$TaskId")
    $jobCount=[int](Invoke-MySQL "SELECT COUNT(*) FROM runtime_jobs WHERE task_id=$TaskId AND execution_id='$ExecutionId'")
    $eventCount=[int](Invoke-MySQL "SELECT COUNT(*) FROM processed_runtime_events WHERE event_id='$EventId'")
    $groupRaw=docker exec $KafkaName /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 --describe --group $Group 2>$null
    $groupLine=@($groupRaw | Where-Object {$_ -match [regex]::Escape($Topic)})[-1]
    $columns=($groupLine.Trim() -split "\s+");$currentOffset=[int64]$columns[3];$logEnd=[int64]$columns[4];$lag=[int64]$columns[5]
    $runtimeFinal=Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/health" -TimeoutSec 5
    $deadline=(Get-Date).AddSeconds(20);while($runtimeFinal.activeExecutions -ne 0 -and (Get-Date)-lt $deadline){Start-Sleep -Milliseconds 300;$runtimeFinal=Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/health" -TimeoutSec 5}
    $unclosedFinal=@(Select-String -LiteralPath $RuntimeErr -Pattern "Unclosed AIOKafkaProducer" -ErrorAction SilentlyContinue).Count
    if($assistantCount -ne 1 -or $taskCount -ne 1 -or $jobCount -ne 1 -or $eventCount -ne 1 -or $lag -ne 0 -or $runtimeFinal.activeExecutions -ne 0 -or $unclosedFinal -ne 0){throw "final uniqueness/ack assertion failed"}

    $evidence.task = [ordered]@{ taskId=$TaskId;conversationId=$ConversationId;jobId=$JobId;executionId=$ExecutionId;fenceEpoch=$Fence;workerId=$WorkerId;eventId=$EventId }
    $evidence.outage = [ordered]@{ taskStatus=$TaskDuring;jobStatus="RESULT_PENDING";outboxRows=1;attemptCount=$outboxState.attemptCount;produceFailed=$runtimeDuring.resultTransport.produceFailed;unclosedWarnings=$unclosedDuring }
    $evidence.recovery = [ordered]@{ taskStatus="COMPLETED";jobStatus="COMPLETED";outboxRows=$finalOutbox.rows;topic=$ledgerParts[1];partition=$Partition;offset=$Offset;groupCurrentOffset=$currentOffset;logEndOffset=$logEnd;lag=$lag;activeExecutions=$runtimeFinal.activeExecutions;unclosedWarnings=$unclosedFinal }
    $evidence.uniqueness = [ordered]@{ tasks=$taskCount;jobs=$jobCount;assistantMessages=$assistantCount;processedEvents=$eventCount }
    $evidence.result = "PASS"
    Add-Time "business_terminal_ack_and_uniqueness_verified" @{ taskId=$TaskId;jobId=$JobId;eventId=$EventId;offset=$Offset;lag=$lag;assistantMessages=$assistantCount }
}
catch {
    $evidence.result = "FAIL"
    $evidence.failureType = $_.Exception.GetType().Name
    $evidence.failureMessage = ($_.Exception.Message -replace '(?i)(token|password|secret|key)=[^\s]+','$1=[REDACTED]')
    $diagnostics=[ordered]@{}
    foreach($logItem in @(@{name="goStdout";path=$GoLog},@{name="goStderr";path=$GoErr},@{name="runtimeStdout";path=$RuntimeLog},@{name="runtimeStderr";path=$RuntimeErr})) {
        if(Test-Path -LiteralPath $logItem.path) {
            $tail=((Get-Content -LiteralPath $logItem.path -Tail 30) -join "`n")
            $tail=$tail.Replace($InternalToken,"[REDACTED]").Replace($JwtSecret,"[REDACTED]").Replace($GovernanceKey,"[REDACTED]").Replace($VerificationPepper,"[REDACTED]").Replace($MySQLPassword,"[REDACTED]").Replace($Password,"[REDACTED]")
            $diagnostics[$logItem.name]=$tail
        }
    }
    try { $diagnostics.runtimeHealth=Invoke-RestMethod -Uri "http://127.0.0.1:$RuntimePort/health" -TimeoutSec 3 } catch {}
    $evidence.failureDiagnostics=$diagnostics
    throw
}
finally {
    $evidence.timeline = $Timeline
    Stop-LocalProcess $RuntimeProcess
    Stop-LocalProcess $GoProcess
    foreach($key in $oldEnv.Keys){[Environment]::SetEnvironmentVariable($key,$oldEnv[$key],"Process")}
    $evidence.runtimeWarningCounts = [ordered]@{ unclosedAIOKafkaProducer = @(Select-String -LiteralPath $RuntimeErr -Pattern "Unclosed AIOKafkaProducer" -ErrorAction SilentlyContinue).Count }
    $evidence | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    foreach($name in $CreatedContainers){ if((docker ps -a --format "{{.Names}}") -contains $name){ docker rm -f -v $name | Out-Null } }
    if(Test-Path -LiteralPath $TempRoot){Remove-Item -LiteralPath $TempRoot -Recurse -Force}
    Write-Output "P21_EVIDENCE=$EvidencePath"
}

if($evidence.result -ne "PASS"){exit 1}
Write-Output "P21 FINAL TASK OUTAGE: PASS"
