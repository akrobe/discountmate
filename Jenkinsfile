pipeline {
  agent any

  options {
    timestamps()
    buildDiscarder(logRotator(numToKeepStr: '20'))
    // We do our own checkout stage
    skipDefaultCheckout(true)
  }

  // UI toggles
  parameters {
    booleanParam(name: 'DEPLOY_STAGING',    defaultValue: true, description: 'Deploy to staging on every build')
    booleanParam(name: 'DEPLOY_TO_PROD',    defaultValue: true, description: 'Promote to prod after quality & security gates')
    booleanParam(name: 'AUTO_APPROVE_PROD', defaultValue: true, description: 'Skip manual approval')
    booleanParam(name: 'RUN_MONITORING', defaultValue: false, description: 'Start Prometheus/Alertmanager and fire a test alert (optional)')
  }

  // Ensure docker binaries are discoverable on macOS agents
  environment {
    PATH = "/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
    REGISTRY = 'ghcr.io'
    IMAGE_REPO = 'ghcr.io/akrobe/discountmate'
    DOCKER_BUILDKIT = '1'
    COMPOSE_DOCKER_CLI_BUILD = '1'
    SONARQUBE_SERVER = 'SonarQube'
  }

  stages {

    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Init') {
      steps {
        sh '''set -eux
mkdir -p reports env
GIT_SHA=$(git rev-parse --short HEAD)
DATE=$(date +%Y.%m.%d)
BUILD_NO=${BUILD_NUMBER:-0}
VERSION="${DATE}-${BUILD_NO}-${GIT_SHA}"
echo "VERSION=$VERSION" | tee reports/version.txt
'''
        script {
          env.VERSION = sh(script: "awk -F= '/^VERSION=/{print \$2}' reports/version.txt", returnStdout: true).trim()
        }
        archiveArtifacts artifacts: 'reports/version.txt', fingerprint: true
      }
    }

    stage('Docker Sanity') {
      steps {
        sh '''set -eux
echo "PATH=$PATH"
command -v docker
docker version
docker compose version
docker buildx version
docker buildx inspect ci-builder || docker buildx create --use --name ci-builder
docker buildx inspect --bootstrap
'''
      }
    }

    stage('Build') {
      steps {
        script {
          try {
            withCredentials([usernamePassword(credentialsId: 'ghcr_pat', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh '''set -eux
echo "$GH_PAT" | docker login ${REGISTRY} -u "$GH_USER" --password-stdin
docker buildx build --platform linux/arm64 --load \
  -t ${IMAGE_REPO}:${VERSION}-local -f Dockerfile .
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ${IMAGE_REPO}:${VERSION} -t ${IMAGE_REPO}:latest \
  -f Dockerfile --push .
'''
            }
          } catch (ignored) {
            // Fallback to the github-https creds if PAT id isn't present
            withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh '''set -eux
echo "$GH_PAT" | docker login ${REGISTRY} -u "$GH_USER" --password-stdin
docker buildx build --platform linux/arm64 --load \
  -t ${IMAGE_REPO}:${VERSION}-local -f Dockerfile .
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ${IMAGE_REPO}:${VERSION} -t ${IMAGE_REPO}:latest \
  -f Dockerfile --push .
'''
            }
          }
        }
      }
    }

    stage('Test (unit)') {
      steps {
        sh '''set -eux
mkdir -p reports
docker run --rm -v "$WORKSPACE:/workspace" -w /workspace -e PYTHONPATH=/workspace ${IMAGE_REPO}:${VERSION}-local sh -lc '
  pip install -r requirements.txt -r requirements-dev.txt &&
  pytest -q \
    --junitxml=reports/junit.xml \
    --cov=app \
    --cov-report=xml:reports/coverage.xml \
    --cov-report=html:reports/htmlcov \
    --cov-fail-under=35 \
    tests/test_unit_*.py
'
'''
      }
      post {
        always {
          junit(testResults: 'reports/junit.xml', allowEmptyResults: false)
          publishHTML(target: [allowMissing: true, alwaysLinkToLastBuild: true, keepAll: true,
            reportDir: 'reports/htmlcov', reportFiles: 'index.html', reportName: 'Coverage (HTML)'])
          archiveArtifacts artifacts: 'reports/coverage.xml', fingerprint: true
        }
      }
    }

    stage('Test (integration)') {
      steps {
        sh '''set -eux
docker rm -f dm_svc || true
docker run -d --rm --name dm_svc -p 0:8080 ${IMAGE_REPO}:${VERSION}-local
HOST_PORT=$(docker port dm_svc 8080/tcp | head -n1 | awk -F: '{print $NF}')
for i in $(seq 1 30); do curl -fsS "http://localhost:$HOST_PORT/health" && break || sleep 1; done

docker run --rm \
  -v "$WORKSPACE:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace \
  -e BASE_URL="http://host.docker.internal:${HOST_PORT}" \
  ${IMAGE_REPO}:${VERSION}-local sh -lc "
  pip install -r requirements.txt -r requirements-dev.txt && \
  pytest -q --junitxml=reports/junit-it.xml tests/test_integration_*.py
"

docker rm -f dm_svc || true
'''
      }
      post {
        always {
          junit(testResults: 'reports/junit-it.xml', allowEmptyResults: false)
        }
      }
    }

stage('Code Quality (SonarQube)') {
  steps {
    sh '''
      set -eux
      docker rm -f sonarqube || true
      docker run -d --name sonarqube -p 9000:9000 sonarqube:lts-community

      # wait until SQ is up
      for i in $(seq 1 60); do curl -sf http://localhost:9000/api/server/version && break || sleep 2; done
    '''
    withCredentials([usernamePassword(credentialsId: 'sonar-admin', usernameVariable: 'SQ_USER', passwordVariable: 'SQ_PASS')]) {
      sh '''
        docker run --rm -v "$WORKSPACE:/usr/src" sonarsource/sonar-scanner-cli:5 \
          -Dsonar.host.url=http://host.docker.internal:9000 \
          -Dsonar.login=$SQ_USER \
          -Dsonar.password=$SQ_PASS
      '''
    }
  }
  post {
    always {
      echo 'SonarQube analysis complete (see UI at http://localhost:9000).'
    }
  }
}

    stage('Security (Bandit, pip-audit, Trivy)') {
  steps {
    // Bandit (non-blocking, high severity only)
    sh '''set -eux
mkdir -p reports
docker run --rm -v "$WORKSPACE:/src" python:3.12-slim sh -lc '
  pip install --no-cache-dir bandit && cd /src &&
  bandit -r app -f json -o reports/bandit.json --severity-level high --confidence-level high || true
'
'''
    script {
      // pip-audit (strict)
      int pipAuditStatus = sh(
        returnStatus: true,
        script: '''
          docker run --rm -v "$WORKSPACE:/src" python:3.12-slim sh -lc '
            pip install --no-cache-dir pip-audit && cd /src &&
            pip-audit -r requirements.txt --format json -o reports/pip-audit.json --strict
          '
        '''
      )

      // Trivy (HIGH/CRITICAL) scan the local image built above
      int trivyStatus = sh(
        returnStatus: true,
        script: """
          docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$WORKSPACE:/src" aquasec/trivy:0.54.1 image \
            --format json --output /src/reports/trivy.json \
            --severity CRITICAL,HIGH --exit-code 1 ${IMAGE_REPO}:${VERSION}-local
        """
      )

      // Gate logic (with timeout around manual approval)
      if (pipAuditStatus != 0 || trivyStatus != 0) {
        if (params.DEPLOY_TO_PROD) {
          if (params.AUTO_APPROVE_PROD) {
            error('Security gate failed and AUTO_APPROVE_PROD is true. Failing the build.')
          } else {
            timeout(time: 15, unit: 'MINUTES') {
              input message: 'Security gate failed (pip-audit or Trivy). Proceed to production anyway?', ok: 'Proceed'
            }
          }
        } else {
          echo 'Security gate failed but DEPLOY_TO_PROD is disabled; continuing.'
        }
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'reports/*.json', fingerprint: true
    }
  }
}

    stage('Deploy: Staging (compose + gate)') {
      when { expression { return params.DEPLOY_STAGING } }
      steps {
        sh '''set -eux
APP_PORT="$(awk -F= '/^APP_PORT=/{print $2}' env/.env.staging || echo 8081)"
export IMAGE="${IMAGE_REPO}:${VERSION}"
docker compose -f docker-compose.yml --env-file env/.env.staging --profile staging up -d discountmate
for i in $(seq 1 30); do curl -sf "http://localhost:${APP_PORT}/health" && break || sleep 1; done
'''
      }
    }

    stage('Approve Release') {
  when { expression { params.DEPLOY_TO_PROD && !params.AUTO_APPROVE_PROD } }
  options { timeout(time: 30, unit: 'MINUTES') }
  steps { input message: "Promote ${env.VERSION} to production?", ok: 'Ship it' }
}

    stage('Release: Prod (multi-arch tag + compose)') {
      when { expression { return params.DEPLOY_TO_PROD } }
      steps {
        script {
          try {
            withCredentials([usernamePassword(credentialsId: 'ghcr_pat', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh '''set -eux
echo "$GH_PAT" | docker login ${REGISTRY} -u "$GH_USER" --password-stdin
docker buildx imagetools create --tag ${IMAGE_REPO}:prod ${IMAGE_REPO}:${VERSION}
docker buildx imagetools inspect ${IMAGE_REPO}:prod
'''
            }
          } catch (ignored) {
            withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh '''set -eux
echo "$GH_PAT" | docker login ${REGISTRY} -u "$GH_USER" --password-stdin
docker buildx imagetools create --tag ${IMAGE_REPO}:prod ${IMAGE_REPO}:${VERSION}
docker buildx imagetools inspect ${IMAGE_REPO}:prod
'''
            }
          }

          // Always deploy/verify prod after tagging
          sh '''set -eux
mkdir -p env
# Use an unprivileged port by default
[ -f env/.env.production ] || echo "APP_PORT=8082" > env/.env.production
APP_PORT="$(awk -F= '/^APP_PORT=/{print $2}' env/.env.production || echo 8082)"
export IMAGE="${IMAGE_REPO}:${VERSION}"

docker compose -f docker-compose.yml --env-file env/.env.production --profile prod up -d discountmate --remove-orphans

# Wait up to 60s and show logs if the health check fails
for i in $(seq 1 60); do
  curl -sf "http://localhost:${APP_PORT}/health" && break || sleep 1
done

curl -sf "http://localhost:${APP_PORT}/health" || {
  echo "Health check failed on port ${APP_PORT}"
  docker compose -f docker-compose.yml --env-file env/.env.production --profile prod ps
  docker compose -f docker-compose.yml --env-file env/.env.production --profile prod logs --tail=200 discountmate || true
  exit 1
}
'''
        }
      }
    }

    stage('Monitoring & Alerting (Prom+BB+AM)') {
  when { expression { params.DEPLOY_TO_PROD && params.RUN_MONITORING && fileExists('docker-compose.monitoring.yml') } }
  steps {
    catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE') {
      sh '''set -eux
# bring up monitoring with random Alertmanager port
ALERTMGR_PORT=0 docker compose -f docker-compose.monitoring.yml --profile monitoring up -d

# discover the published AM port
AM_PORT="$(docker compose -f docker-compose.monitoring.yml port alerts 9093 | awk -F: '{print $NF}')"

# wait for Prom + AM
for i in $(seq 1 60); do curl -sf http://localhost:9090/-/ready && break || sleep 1; done
for i in $(seq 1 60); do curl -sf "http://localhost:${AM_PORT}/api/v2/status" && break || sleep 1; done

# all targets health
curl -s http://localhost:9090/api/v1/targets | jq -r '
  .data.activeTargets | [.[].health] as $h
  | "up=" + ([$h[]|select(.=="up")]|length|tostring) + " " +
    "down=" + ([$h[]|select(.=="down")]|length|tostring)'

# ensure blackbox-http job is up
curl -s http://localhost:9090/api/v1/targets \
 | jq -e '.data.activeTargets[] | select(.labels.job=="blackbox-http" and .health=="up")' >/dev/null

# simulate outage
docker compose -f docker-compose.yml --env-file env/.env.production --profile prod stop discountmate || true
sleep 45

# expect AppDown
curl -s "http://localhost:${AM_PORT}/api/v2/alerts" \
 | jq -e '.[] | select(.labels.alertname=="AppDown")' >/dev/null || echo "Warning: expected alert not found"

# recover
docker compose -f docker-compose.yml --env-file env/.env.production --profile prod up -d discountmate
'''
    }
  }
}

    stage('Gate Debug') {
      steps { echo "PUSHED=true DEPLOY_STAGING=${params.DEPLOY_STAGING} DEPLOY_TO_PROD=${params.DEPLOY_TO_PROD} AUTO_APPROVE_PROD=${params.AUTO_APPROVE_PROD}" }
    }
  }

  post {
    always { echo 'Build finished.' }
  }
}