pipeline {
    agent {
        docker {
            reuseNode false
            image 'caufieldjh/ubuntu20-python-3-8-5-dev:4-with-dbs-v6'
        }
    }
    // No scheduled builds for now
    //triggers{
    //    cron('H H 1 1-12 *')
    //}
    environment {
        BUILDSTARTDATE = sh(script: "echo `date +%Y%m%d`", returnStdout: true).trim()
        S3BUCKETNAME = 'kg-hub-public-data'
        S3PROJECTDIR = 'kg-bioportal' // no trailing slash
        MERGEDKGNAME_BASE = "kg_bioportal"
        MERGEDKGNAME_GENERIC = "merged-kg"
    }
    options {
        timestamps()
        disableConcurrentBuilds()
    }
    stages {
        // Very first: pause for a minute to give a chance to
        // cancel and clean the workspace before use.
        stage('Ready and clean') {
            steps {
                // Give us a minute to cancel if we want.
                sleep time: 30, unit: 'SECONDS'
            }
        }

        stage('Initialize') {
            steps {
                // print some info
                dir('./gitrepo') {
                    sh 'env > env.txt'
                    sh 'echo $BRANCH_NAME > branch.txt'
                    sh 'echo "$BRANCH_NAME"'
                    sh 'cat env.txt'
                    sh 'cat branch.txt'
                    sh "echo $BUILDSTARTDATE > dow.txt"
                    sh "echo $BUILDSTARTDATE"
                    sh "echo $MERGEDKGNAME_BASE"
                    sh "echo $MERGEDKGNAME_GENERIC"
                    sh "python3.8 --version"
                    sh "id"
                    sh "whoami" // this should be jenkinsuser
                    // if the above fails, then the docker host didn't start the docker
                    // container as a user that this image knows about. This will
                    // likely cause lots of problems (like trying to write to $HOME
                    // directory that doesn't exist, etc), so we should fail here and
                    // have the user fix this

                }
            }
        }

        stage('Build kg_bioportal') {
            steps {
                dir('./gitrepo') {
                    git(
                            url: 'https://github.com/Knowledge-Graph-Hub/kg-bioportal',
                            branch: env.BRANCH_NAME
                    )
                    sh '/usr/bin/python3.8 -m venv venv'
                    sh '. venv/bin/activate'
                    // Now move on to the actual install + reqs
                    sh './venv/bin/pip install .'
                    sh './venv/bin/pip install awscli boto3 s3cmd'
                }
            }
        }

        // the download step uses s3cmd instead of the standard kghub_downloader
        // this is so we can access the private object

        stage('Download') {
            steps {
                dir('./gitrepo') {
                    script {
                        
                        // Verify that the project directory is defined, or it will make a mess
                        // when it uploads everything to the wrong directory
                        if (S3PROJECTDIR.replaceAll("\\s","") == '') {
                            error("Project name contains only whitespace. Will not continue.")
                        }
                        withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                            sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG get s3://$S3BUCKETNAME/frozen_incoming_data/bioportal_transformed/bioportal_transformed.tar.gz data/raw/bioportal_transformed.tar.gz'
                        }

                    }
                }
            }
        }

        // Transform step just moves and decompresses the raw sources
        
        stage('Transform') {
           steps {
               dir('./gitrepo') {
		           sh '. venv/bin/activate && env && mv data/raw/* data/merged/ && tar -xvzf data/merged/bioportal_transformed.tar.gz'
               }
           }
        }

        stage('Merge') {
            steps {
                dir('./gitrepo') {
                    sh '. venv/bin/activate && python3.8 run.py merge --merge_all'
                    sh 'cp merged_graph_stats.yaml merged_graph_stats_$BUILDSTARTDATE.yaml'
                    sh 'tar -rvfz data/merged/merged-kg.tar.gz merged_graph_stats_$BUILDSTARTDATE.yaml'
                }
            }
        }

        stage('Publish') {
            steps {
                dir('./gitrepo') {
                    script {

                        // make sure we aren't going to clobber existing data
                        withCredentials([file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG')]) {
                            REMOTE_BUILD_DIR_CONTENTS = sh (
                                script: '. venv/bin/activate && s3cmd -c $S3CMD_CFG ls s3://$S3BUCKETNAME/$S3PROJECTDIR/$BUILDSTARTDATE/',
                                returnStdout: true
                            ).trim()
                            echo "REMOTE_BUILD_DIR_CONTENTS (THIS SHOULD BE EMPTY): '${REMOTE_BUILD_DIR_CONTENTS}'"
                            if("${REMOTE_BUILD_DIR_CONTENTS}" != ''){
                                echo "Will not overwrite existing remote S3 directory: $S3PROJECTDIR/$BUILDSTARTDATE"
                                sh 'exit 1'
                            } else {
                                echo "remote directory $S3PROJECTDIR/$BUILDSTARTDATE is empty, proceeding"
                            }
                        }

                        if (env.BRANCH_NAME != 'main') {
                            echo "Will not push if not on main branch."
                        } else {
                            withCredentials([
					            file(credentialsId: 's3cmd_kg_hub_push_configuration', variable: 'S3CMD_CFG'),
					            file(credentialsId: 'aws_kg_hub_push_json', variable: 'AWS_JSON'),
					            string(credentialsId: 'aws_kg_hub_access_key', variable: 'AWS_ACCESS_KEY_ID'),
					            string(credentialsId: 'aws_kg_hub_secret_key', variable: 'AWS_SECRET_ACCESS_KEY')]) {
                                 
                                //
                                // make $BUILDSTARTDATE/ directory and sync to s3 bucket
                                // Don't create any index - none of this will be public
                                //
                                sh 'mkdir $BUILDSTARTDATE/'
                                sh 'cp -p data/merged/merged-kg.tar.gz $BUILDSTARTDATE/${MERGEDKGNAME_BASE}.tar.gz'
                                sh 'cp Jenkinsfile $BUILDSTARTDATE/'
                                // stats dir
                                sh 'mkdir $BUILDSTARTDATE/stats/'
                                sh 'cp -p *_stats.yaml $BUILDSTARTDATE/stats/'

                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr $BUILDSTARTDATE s3://$S3BUCKETNAME/$S3PROJECTDIR/'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG rm -r s3://$S3BUCKETNAME/$S3PROJECTDIR/current/'
                                sh '. venv/bin/activate && s3cmd -c $S3CMD_CFG put -pr $BUILDSTARTDATE/* s3://$S3BUCKETNAME/$S3PROJECTDIR/current/'

                            }

                        }
                    }
                }
            }
        }

    }

    post {
        always {
            echo 'In always'
            echo 'Cleaning workspace...'
            cleanWs()
        }
        success {
            echo 'I succeeded!'
        }
        unstable {
            echo 'I am unstable :/'
        }
        failure {
            echo 'I failed :('
        }
        changed {
            echo 'Things were different before...'
        }
    }
}
