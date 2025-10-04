pipeline {
  agent any
  options {
    buildDiscarder(logRotator(numToKeepStr: '20'))
    timestamps()
  }

  parameters {
    booleanParam(name: 'DO_SONAR', defaultValue: false, description: 'Enable SonarQube analysis + Quality Gate')
  }

  environment {
    APP_NAME = 'discountmate'
    REGISTRY = "ghcr.io/${env.GIT_USERNAME ?: 'akrobe'}"   // change if needed
    IMAGE_BASENAME = "${REGISTRY}/${APP_NAME}"
  }

  stages {
    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Init') {
      steps {
        script {
          env.SHORT_SHA = sh(script: "git rev-parse --short HEAD", returnStdout: true).trim()
          env.VERSION   = sh(script: "date +%Y.%m.%d", returnStdout: true).trim() + "-${env.BUILD_NUMBER}-${env.SHORT_SHA}"
          env.IMAGE_TAG = "${env.IMAGE_BASENAME}:${env.VERSION}"
        }
        sh 'mkdir -p reports'
        echo "VERSION=${env.VERSION}"
      }
    }

    stage('Build (Docker → GHCR)') {
      steps {
        withCredentials([string(credentialsId: 'ghcr-pat', variable: 'PAT')]) {
          sh '''
            echo "$PAT" | docker login ghcr.io -u akrobe --password-stdin
            docker build -t ${IMAGE_TAG} .
            docker tag ${IMAGE_TAG} ${IMAGE_BASENAME}:latest
            docker push ${IMAGE_TAG}
            docker push ${IMAGE_BASENAME}:latest
          '''
        }
      }
    }

    stage('Test (unit + integration)') {
      steps {
        sh '''
          set -eux
          if [ -f requirements-dev.txt ] && [ -d tests ]; then
            docker run --rm --name dm_unit ${IMAGE_TAG} \
              sh -lc "pip install -r requirements-dev.txt && \
                      pytest -q --junitxml=reports/junit.xml --cov=app --cov-report=xml:reports/coverage.xml tests/test_unit_model.py"

            docker run -d --rm --name dm_svc -p 8088:8080 ${IMAGE_TAG}
            sleep 3
            docker run --rm --network=host -e TEST_IMAGE=${IMAGE_TAG} ${IMAGE_TAG} \
              sh -lc "pip install -r requirements-dev.txt && \
                      pytest -q --junitxml=reports/junit-it.xml tests/test_integration_api.py"
            docker stop dm_svc
          else
            echo "No tests yet; running smoke…"
            docker run -d --rm --name dm_smoke -p 8088:8080 ${IMAGE_TAG}
            sleep 3
            curl -sf http://localhost:8088/health > /dev/null
            docker stop dm_smoke
          fi
        '''
      }
      post { always { junit allowEmptyResults: true, testResults: 'reports/*.xml' } }
    }

    stage('Code Quality (SonarQube)') {
      when { expression { return params.DO_SONAR } }
      steps {
        withSonarQubeEnv('SonarQube') {
          sh '''
            docker run --rm -v $PWD:/usr/src sonarsource/sonar-scanner-cli \
              -Dsonar.projectKey=discountmate \
              -Dsonar.sources=app \
              -Dsonar.tests=tests \
              -Dsonar.python.version=3.12 \
              -Dsonar.junit.reportPaths=reports/junit.xml,reports/junit-it.xml \
              -Dsonar.coverageReportPaths=reports/coverage.xml \
              -Dsonar.host.url=$SONAR_HOST_URL \
              -Dsonar.login=$SONAR_AUTH_TOKEN
          '''
        }
      }
    }

    stage('Quality Gate') {
      when { expression { return params.DO_SONAR } }
      steps {
        timeout(time: 15, unit: 'MINUTES') {
          waitForQualityGate abortPipeline: true
        }
      }
    }

    stage('Security (Bandit, pip-audit, Trivy)') {
      steps {
        sh '''
          set +e
          mkdir -p reports
          docker run --rm -v $PWD:/src python:3.12-slim sh -lc "
            pip install --no-cache-dir bandit pip-audit && \
            cd /src && \
            bandit -r app -f json -o reports/bandit.json || true && \
            pip-audit -r requirements.txt -f json -o reports/pip-audit.json || true"
          docker run --rm aquasec/trivy:latest image --exit-code 1 --severity CRITICAL ${IMAGE_TAG} > reports/trivy.txt || true

          # Gate: fail if Bandit HIGH > 0 or Trivy output contains CRITICAL
          python3 - <<'PY'
import json, os, sys
try:
    d=json.load(open('reports/bandit.json'))
    high=sum(1 for r in d.get('results',[]) if r.get('issue_severity')=='HIGH')
except Exception:
    high=0
print("Bandit HIGH:", high)
sys.exit(1 if high>0 else 0)
PY
          grep -q 'CRITICAL' reports/trivy.txt && echo 'Trivy CRITICAL found' && exit 1 || echo 'No Trivy CRITICAL'
        '''
      }
      post { always { archiveArtifacts artifacts: 'reports/*.json, reports/*.txt', fingerprint: true } }
    }

    stage('Deploy: Staging (compose + health gate)') {
      steps {
        sh '''
          export ENV_FILE=env/.env.staging
          export IMAGE=${IMAGE_TAG}
          docker compose --env-file ${ENV_FILE} --profile staging up -d
          for i in $(seq 1 30); do
            curl -sf http://localhost:8081/health && break || sleep 2
          done
          curl -sf http://localhost:8081/health > /dev/null
        '''
      }
    }

    stage('Release: Approve & Promote to Prod') {
      steps {
        input message: 'Approve release to PRODUCTION?', ok: 'Release'
        withCredentials([string(credentialsId: 'ghcr-pat', variable: 'PAT')]) {
          sh '''
            echo "$PAT" | docker login ghcr.io -u akrobe --password-stdin
            docker pull ${IMAGE_TAG}
            docker tag ${IMAGE_TAG} ${IMAGE_BASENAME}:prod
            docker push ${IMAGE_BASENAME}:prod

            export ENV_FILE=env/.env.production
            export IMAGE=${IMAGE_BASENAME}:prod
            docker compose --env-file ${ENV_FILE} --profile prod up -d

            for i in $(seq 1 30); do
              curl -sf http://localhost/health && break || sleep 2
            done
            curl -sf http://localhost/health > /dev/null

            echo "${VERSION}" > reports/release.txt
          '''
        }
      }
      post { success { archiveArtifacts artifacts: 'reports/release.txt', fingerprint: true } }
    }

    stage('Monitoring & Alerting (demo)') {
      steps {
        sh '''
          curl -s -XPOST http://localhost:8081/recommend -H 'content-type: application/json' \
               -d '{"total":220,"items":5,"tier":"silver"}' > /dev/null || true
          curl -s -XPOST http://localhost:8081/simulate_error > /dev/null || true

          sleep 70
          curl -sf http://localhost:9093/api/v2/alerts -o reports/alerts.json || true
          python3 - <<'PY'
import json, sys
try:
  data=json.load(open('reports/alerts.json'))
  ok=any(a.get('labels',{}).get('alertname')=='DiscountmateErrors' for a in data)
  sys.exit(0 if ok else 1)
except Exception:
  sys.exit(1)
PY
        '''
      }
      post { always { archiveArtifacts artifacts: 'reports/*.json', fingerprint: true } }
    }
  }

  post {
    success { echo "Pipeline OK: ${env.VERSION}" }
    failure { echo "Pipeline FAILED" }
  }
}