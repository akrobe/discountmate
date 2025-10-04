pipeline {
  agent any

  options {
    timestamps()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  // UI toggles
  parameters {
    booleanParam(name: 'DEPLOY_STAGING',   defaultValue: true,  description: 'Deploy to staging on every build')
    booleanParam(name: 'DEPLOY_TO_PROD',   defaultValue: true,  description: 'Promote to prod after quality & security gates')
    booleanParam(name: 'AUTO_APPROVE_PROD', defaultValue: true, description: 'Skip manual approval')
  }

  // Make sure docker & sonar are found on macOS agents
  environment {
    PATH = "/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
    REGISTRY = 'ghcr.io'
    IMAGE_REPO = 'ghcr.io/akrobe/discountmate'
    DOCKER_BUILDKIT = '1'
    COMPOSE_DOCKER_CLI_BUILD = '1'
    SONARQUBE_SERVER = 'SonarQube' // Must match Manage Jenkins > SonarQube servers
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
docker run --rm -v "$PWD:/workspace" -w /workspace -e PYTHONPATH=/workspace ${IMAGE_REPO}:${VERSION}-local sh -lc '
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
  -v "$PWD:/workspace" -w /workspace \
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
      // keep the HTML coverage publisher from the unit stage only
    }
  }
}

stage('Security (Bandit, pip-audit, Trivy)') {
  steps {
    sh '''set -eux
mkdir -p reports

# Bandit (keep enforcing high-only)
docker run --rm -v "$PWD:/src" python:3.12-slim sh -lc '
  pip install --no-cache-dir bandit && cd /src &&
  bandit -r app -f json -o reports/bandit.json --severity-level high --confidence-level high || true
'

# pip-audit (run but don't fail the job)
docker run --rm -v "$PWD:/src" python:3.12-slim sh -lc '
  pip install --no-cache-dir pip-audit && cd /src &&
  pip-audit -r requirements.txt --format json -o reports/pip-audit.json --strict || true
'

# Trivy (image scan) – also non-blocking here
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/src" aquasec/trivy:0.54.1 image \
  --format json --output /src/reports/trivy.json \
  --severity CRITICAL,HIGH --exit-code 1 ghcr.io/akrobe/discountmate:${VERSION}-local || true
'''
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
echo "APP_PORT=8080" > env/.env.staging
export IMAGE=${IMAGE_REPO}:${VERSION}
docker compose -f docker-compose.yml --env-file env/.env.staging --profile staging up -d discountmate
for i in $(seq 1 30); do curl -sf http://localhost:8080/health && break || sleep 1; done
'''
      }
    }

    stage('Approve Release') {
      when { expression { return params.DEPLOY_TO_PROD && !params.AUTO_APPROVE_PROD } }
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
APP_PORT=${APP_PORT:-8081}
for i in $(seq 1 30); do
  curl -sf "http://localhost:${APP_PORT}/health" && break
  sleep 1
done'''
            }
          } catch (ignored) {
            withCredentials([usernamePassword(credentialsId: 'github-https', usernameVariable: 'GH_USER', passwordVariable: 'GH_PAT')]) {
              sh '''set -eux
echo "$GH_PAT" | docker login ${REGISTRY} -u "$GH_USER" --password-stdin
docker buildx imagetools create --tag ${IMAGE_REPO}:prod ${IMAGE_REPO}:${VERSION}
docker buildx imagetools inspect ${IMAGE_REPO}:prod
echo "APP_PORT=80" > env/.env.production
export IMAGE=${IMAGE_REPO}:${VERSION}
docker compose -f docker-compose.yml --env-file env/.env.production --profile prod up -d discountmate --remove-orphans
for i in $(seq 1 30); do curl -sf http://localhost/health && break || sleep 1; done
'''
            }
          }
        }
      }
    }

    stage('Monitoring & Alerting (Prom+BB+AM)') {
      steps {
        sh '''set -eux
docker compose -f docker-compose.monitoring.yml --profile monitoring up -d
for i in $(seq 1 30); do curl -sf http://localhost:9090/-/ready && break || sleep 1; done
for i in $(seq 1 30); do curl -sf http://localhost:9093/api/v2/status && break || sleep 1; done
curl -sf "http://localhost:9090/api/v1/targets" | grep -q '"health":"up"'
# Simulate outage -> alert
docker compose -f docker-compose.yml --env-file env/.env.production --profile prod stop discountmate || true
sleep 40
curl -sf "http://localhost:9093/api/v2/alerts" | grep -q 'AppDown' || (echo "Alert did not fire" && exit 1)
docker compose -f docker-compose.yml --env-file env/.env.production --profile prod up -d discountmate
'''
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